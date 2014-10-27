"""
Copyright (c) 2014, CloudSigma AG
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the CloudSigma AG nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL CLOUDSIGMA AG BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import logging

import os

from .controllers import CpuAcctController, CpuController, CpuSetController, MemoryController
from .utils import walk_tree


LOG = logging.getLogger(__name__)


class Node(object):

    """
    Basic cgroup tree node. Provides means to link it to a parent and set a controller, depending on the cgroup the node
    exists in.
    """
    NODE_ROOT = "root"
    NODE_CONTROLLER_ROOT = "controller_root"
    NODE_SLICE = "slice"
    NODE_SCOPE = "scope"
    NODE_CGROUP = "cgroup"

    CONTROLLERS = {
        "memory": MemoryController,
        "cpuset": CpuSetController,
        "cpu": CpuController,
        "cpuacct": CpuAcctController
    }

    def __init__(self, name, parent=None):
        self.name = name
        self.verbose_name = name.decode("unicode_escape")
        self.parent = parent
        self.children = []
        self.node_type = self._get_node_type()
        self.controller_type = self._get_controller_type()
        self.controller = self._get_controller()

    def __eq__(self, other):
        if isinstance(other, self.__class__) and self.full_path == other.full_path:
            return True
        return False

    def __repr__(self):
        return "<{} {}>".format(self.__class__.__name__, self.path)

    @property
    def full_path(self):
        """Absolute system path to the node"""

        if self.parent:
            return os.path.join(self.parent.full_path, self.name)
        return self.name

    @property
    def path(self):
        """Node's relative path from the root node"""

        if self.parent:
            return os.path.join(self.parent.path, self.name)
        return "/"

    def _get_node_type(self):
        """Returns the current node's type"""

        if self.parent is None:
            return self.NODE_ROOT
        elif self.parent.node_type == self.NODE_ROOT:
            return self.NODE_CONTROLLER_ROOT
        elif ".slice" in self.name or '.partition' in self.name:
            return self.NODE_SLICE
        elif ".scope" in self.name:
            return self.NODE_SCOPE
        else:
            return self.NODE_CGROUP

    def _get_controller_type(self):
        """Returns the current node's controller type"""

        if self.node_type == self.NODE_CONTROLLER_ROOT and self.name in self.CONTROLLERS:
            return self.name
        elif self.parent:
            return self.parent.controller_type
        else:
            return None

    def _get_controller(self):
        """Returns the current node's controller"""

        if self.controller_type:
            return self.CONTROLLERS[self.controller_type](self)
        return None


class NodeControlGroup(object):

    """
    A tree node that can group together same multiple nodes based on their position in the cgroup hierarchy

    For example - we have mounted all the cgroups in /sys/fs/cgroup/ and we have a scope in each of them under
    /{cpuset,cpu,memory,cpuacct}/isolated.scope/. Then NodeControlGroup, can provide access to all cgroup properties
    like

    isolated_scope.cpu
    isolated_scope.memory
    isolated_scope.cpuset

    Requires a basic Node tree to be generated.
    """

    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.children_map = {}
        self.controllers = {}
        self.nodes = []

    @property
    def path(self):
        if self.parent:
            base_name, ext = os.path.splitext(self.name)
            if ext not in ['.slice', '.scope', '.partition']:
                base_name = self.name
            return os.path.join(self.parent.path, base_name)
        return "/"

    def add_node(self, node):
        """
        A a Node object to the group. Only one node per cgroup is supported
        """
        if self.controllers.get(node.controller_type, None):
            raise Exception("Cannot add node {} to the node group. A node for {} group is already assigned".format(
                node,
                node.controller_type
            ))
        self.nodes.append(node)
        if node.controller:
            self.controllers[node.controller_type] = node.controller
            setattr(self, node.controller_type, node.controller)

    def __repr__(self):
        return "<{} {}>".format(self.__class__.__name__, self.name)

    @property
    def children(self):
        return self.children_map.values()

    @property
    def group_tasks(self):
        """All tasks in the hierarchy, affected by this group."""
        tasks = set()
        for node in walk_tree(self):
            for ctrl in node.controllers.values():
                tasks.update(ctrl.tasks)
        return tasks

    @property
    def tasks(self):
        """Tasks in this exact group"""
        tasks = set()
        for ctrl in self.controllers.values():
            tasks.update(ctrl.tasks)
        return tasks


class NodeVM(NodeControlGroup):

    """Abstraction of a QEMU virtual machine node."""

    @property
    def verbose_name(self):
        try:
            return self.nodes[0].verbose_name
        except:
            return "AnonymousVM"

    @property
    def emulator(self):
        return self.children_map.get("emulator", None)

    @property
    def vcpus(self):
        return [node for name, node in self.children_map.items() if name.startswith("vcpu")]
