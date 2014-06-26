# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013, 2014 Intel Corporation.
# Copyright 2013, 2014 Isaku Yamahata <isaku.yamahata at intel com>
#                                     <isaku.yamahata at gmail com>
# All Rights Reserved.
#
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# @author: Isaku Yamahata, Intel Corporation.

import abc

import six

from tacker.api import extensions
from tacker.openstack.common import jsonutils
from tacker.vm import constants


@six.add_metaclass(abc.ABCMeta)
class DeviceMGMTAbstractDriver(extensions.PluginInterface):

    @abc.abstractmethod
    def get_type(self):
        """Return one of predefined type of the hosting device drivers."""
        pass

    @abc.abstractmethod
    def get_name(self):
        """Return a symbolic name for the service VM plugin."""
        pass

    @abc.abstractmethod
    def get_description(self):
        pass

    def mgmt_create_pre(self, plugin, context, device):
        pass

    def mgmt_create_post(self, plugin, context, device):
        pass

    def mgmt_update_pre(self, plugin, context, device):
        pass

    def mgmt_update_post(self, plugin, context, device):
        pass

    def mgmt_delete_pre(self, plugin, context, device):
        pass

    def mgmt_delete_post(self, plugin, context, device):
        pass

    def mgmt_get_config(self, plugin, context, device):
        """
        returns dict of file-like objects which will be passed to hosting
        device.
        It depends on drivers how to use it.
        for nova case, it can be used for meta data, file injection or
        config drive
        i.e.
        metadata case: nova --meta <key>=<value>
        file injection case: nova --file <dst-path>:<src-path>
        config drive case: nova --config-drive=true --file \
                                <dst-path>:<src-path>
        """
        return {}

    @abc.abstractmethod
    def mgmt_address(self, plugin, context, device):
        pass

    @abc.abstractmethod
    def mgmt_call(self, plugin, context, device, kwargs):
        pass

    def mgmt_service_driver(self, plugin, context, device, service_instance):
        # use same mgmt driver to communicate with service
        return self.get_name()

    def mgmt_service_create_pre(self, plugin, context, device,
                                service_instance):
        pass

    def mgmt_service_create_post(self, plugin, context, device,
                                 service_instance):
        pass

    def mgmt_service_update_pre(self, plugin, context, device,
                                service_instance):
        pass

    def mgmt_service_update_post(self, plugin, context, device,
                                 service_instance):
        pass

    def mgmt_service_delete_pre(self, plugin, context, device,
                                service_instance):
        pass

    def mgmt_service_delete_post(self, plugin, context, device,
                                 service_instance):
        pass

    @abc.abstractmethod
    def mgmt_service_address(self, plugin, context, device, service_instance):
        pass

    @abc.abstractmethod
    def mgmt_service_call(self, plugin, context, device,
                          service_instance, kwargs):
        pass


class DeviceMGMTByNetwork(DeviceMGMTAbstractDriver):
    def mgmt_address(self, plugin, context, device):
        mgmt_entries = [sc_entry for sc_entry in device.service_context
                        if (sc_entry.role == constants.ROLE_MGMT and
                            sc_entry.port_id)]
        if not mgmt_entries:
            return
        port = plugin._core_plugin.get_port(context, mgmt_entries[0].port_id)
        if not port:
            return
        mgmt_address = port['fixed_ips'][0]     # subnet_id and ip_address
        mgmt_address['network_id'] = port['network_id']
        mgmt_address['port_id'] = port['id']
        mgmt_address['mac_address'] = port['mac_address']
        return jsonutils.dumps(mgmt_address)

    def mgmt_service_address(self, plugin, context, device, service_instance):
        mgmt_entries = [sc_entry for sc_entry
                        in service_instance.service_context
                        if (sc_entry.role == constants.ROLE_MGMT and
                            sc_entry.port_id)]
        if not mgmt_entries:
            return
        port = plugin._core_plugin.get_port(context, mgmt_entries[0].port_id)
        if not port:
            return
        mgmt_address = port['fixed_ips'][0]     # subnet_id and ip_address
        mgmt_address['network_id'] = port['network_id']
        mgmt_address['port_id'] = port['id']
        mgmt_address['mac_address'] = port['mac_address']
        return jsonutils.dumps(mgmt_address)
