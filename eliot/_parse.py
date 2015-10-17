"""
Parse a stream of serialized messages into a forest of
``WrittenAction`` and ``WrittenMessage`` objects.

# XXX maybe move Written* here.
"""

from pyrsistent import PClass, field, pmap_field, optional, pvector

from ._message import WrittenMessage
from ._action import (
    TaskLevel, WrittenAction, ACTION_STATUS_FIELD, STARTED_STATUS,
    ACTION_TYPE_FIELD,
)


#@implementer(IWrittenAction)
class MissingAction(PClass):
    _task_level = field(type=TaskLevel, mandatory=True)
    end_message = field(type=optional(WrittenMessage), mandatory=True,
                        initial=None)
    _children = pmap_field(TaskLevel, object)

    @property
    def task_level(self):
        return self._task_level

    @property
    def action_type(self):
        return u"*unknown*"

    @property
    def children(self):
        """
        The list of child messages and actions sorted by task level, excluding the
        start and end messages.
        """
        return pvector(sorted(self._children.values(), key=lambda m: m.task_level))

    def to_written_action(self, start_message):
        return WrittenAction(start_message=start_message,
                             end_message=self.end_message,
                             _children=self._children)


_NODES = (MissingAction, WrittenAction, WrittenMessage)


class Task(PClass):
    """
    A tree of actions with the same task UUID.
    """
    _nodes = pmap_field(TaskLevel, object) # XXX _NODES

    _root_level = TaskLevel(level=[])

    @classmethod
    def create(cls, first_message):
        task = Task()
        return task.add(first_message)

    def root(self):
        return self._nodes[self._root_level]

    def _add_node(self, node):
        return self.transform(["_nodes", node.task_level], node)

    def _ensure_node_parents(self, new_node):
        """
        Ensure the node (WrittenAction/WrittenMessage/MissingAction) is
        referenced by parent nodes.

        MissingAction will be created as necessary.
        """
        task = self
        child = new_node
        task_level = new_node.task_level
        while task_level.parent() is not None:
            parent = self._nodes.get(task_level.parent())
            if parent is None:
                parent = MissingAction(_task_level=task_level.parent())
            parent = parent.transform(["_children", task_level], child)
            task = task._add_node(parent)
            child = parent
            task_level = parent.task_level
        return task

    def add(self, message_dict):
        task = self
        is_action = message_dict.get(ACTION_TYPE_FIELD) is not None
        written_message = WrittenMessage.from_dict(message_dict)
        if is_action:
            action_level = written_message.task_level.parent()
            current_action = self._nodes.get(action_level)
            if current_action is None:
                current_action = MissingAction(_task_level=action_level)
            if message_dict[ACTION_STATUS_FIELD] == STARTED_STATUS:
                new_node = current_action.to_written_action(written_message)
            else:
                new_node = current_action.set(end_message=written_message)
            task = task._add_node(new_node)
        else:
            new_node = written_message
            # Special case where there is no action:
            if new_node.task_level.level == [1]:
                return task.transform(["_nodes", self._root_level], new_node)

        task = task._ensure_node_parents(new_node)
        return task
