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

from tacker.openstack.common import log as logging
from tacker.vm.mgmt_drivers import abstract_driver


LOG = logging.getLogger(__name__)


class DeviceMgmtNoop(abstract_driver.DeviceMGMTAbstractDriver):
    def get_type(self):
        return 'noop'

    def get_name(self):
        return 'noop'

    def get_description(self):
        return 'Tacker DeviceMgmt Noop Driver'

    def mgmt_address(self, plugin, context, device):
        LOG.debug(_('mgmt_address %s'), device)
        return 'noop-mgmt-address'

    def mgmt_call(self, plugin, context, device, kwargs):
        LOG.debug(_('mgmt_device_call %(device)s %(kwargs)s'),
                  {'device': device, 'kwargs': kwargs})

    def mgmt_service_address(self, plugin, context,
                             device, service_instance):
        LOG.debug(_('mgmt_service_address %(device)s %(service_instance)s'),
                  {'device': device, 'service_instance': service_instance})
        return 'noop-mgmt-service-address'

    def mgmt_service_call(self, plugin, context, device,
                          service_instance, kwargs):
        LOG.debug(_('mgmt_service_call %(device)s %(service_instance)s'),
                  {'device': device, 'service_instance': service_instance})
