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

import time

from oslo.config import cfg
from tacker.api.v1 import attributes
from tacker.openstack.common import log as logging
from tacker.vm.drivers import abstract_driver

LOG = logging.getLogger(__name__)
OPTS = [
    cfg.StrOpt('project-id', default='',
               help=_('project id used '
                      'by nova driver of service vm extension')),
    cfg.StrOpt('auth-url', default='http://0.0.0.0:5000/v2.0',
               help=_('auth URL used by nova driver of service vm extension')),
    cfg.StrOpt('user-name', default='',
               help=_('user name used '
                      'by nova driver of service vm extension')),
    cfg.StrOpt('api-key', default='',
               help=_('api-key used by nova driver of service vm extension')),
    cfg.StrOpt('ca-file',
               help=_('Optional CA cert file for nova driver to use in SSL'
                      ' connections ')),
    cfg.BoolOpt('insecure', default=False,
                help=_("If set then the server's certificate will not "
                       "be verified by nova driver")),
]
CONF = cfg.CONF
CONF.register_opts(OPTS, group='servicevm_nova')
_NICS = 'nics'          # converted by novaclient => 'networks'
_NET_ID = 'net-id'      # converted by novaclient => 'uuid'
_PORT_ID = 'port-id'    # converted by novaclient => 'port'
_FILES = 'files'


class DeviceNova(abstract_driver.DeviceAbstractDriver):

    """Nova driver of hosting device."""

    def __init__(self):
        super(DeviceNova, self).__init__()
        from novaclient import client
        from novaclient import shell
        self._novaclient = client
        self._novashell = shell

    def _nova_client(self, token=None):
        computeshell = self._novashell.OpenStackComputeShell()
        extensions = computeshell._discover_extensions("1.1")

        kwargs = {
            'project_id': CONF.servicevm_nova.project_id,
            'auth_url': CONF.servicevm_nova.auth_url,
            'service_type': 'compute',
            'username': CONF.servicevm_nova.user_name,
            'api_key': CONF.servicevm_nova.api_key,
            'extensions': extensions,
            'cacert': CONF.servicevm_nova.ca_file,
            'insecure': CONF.servicevm_nova.insecure,
            # 'http_log_debug': True,
        }
        LOG.debug(_('kwargs %s'), kwargs)
        return self._novaclient.Client("1.1", **kwargs)

    def get_type(self):
        return 'nova'

    def get_name(self):
        return 'nova'

    def get_description(self):
        return 'Nuetron Device Nova driver'

    @staticmethod
    def _safe_pop(d, name_list):
        res = None
        for name in name_list:
            if name in d:
                res = d.pop(name)
                break
        return res

    def _create_port(self, plugin, context, tenant_id,
                     network_id=None, subnet_id=None):
        # resolve subnet and create port
        LOG.debug(_('network_id %(network_id)s subnet_id %(subnet_id)s)'),
                  {'network_id': network_id, 'subnet_id': subnet_id})
        if subnet_id:
            subnet = plugin._core_plugin.get_subnet(context, subnet_id)
            network_id = subnet['network_id']
        port_data = {
            'tenant_id': tenant_id,
            'network_id': network_id,
            'admin_state_up': False,
            'fixed_ips': attributes.ATTR_NOT_SPECIFIED,
        }
        if subnet_id:
            port_data['fixed_ips'] = [{'subnet_id': subnet_id}]

        # See api.v2.base.prepare_request_body()
        for attr, attr_vals in attributes.RESOURCE_ATTRIBUTE_MAP[
                attributes.PORTS].iteritems():
            if not attr_vals.get('allow_post', False):
                continue
            if attr in port_data:
                continue
            port_data[attr] = attr_vals['default']

        LOG.debug(_('port_data %s'), port_data)
        port = plugin._core_plugin.create_port(context, {'port': port_data})
        LOG.debug(_('port %s'), port)
        return port['id']

    def create(self, plugin, context, device):
        # typical required arguments are
        # 'name': name string
        # 'image': uuid
        # 'flavir': uuid
        #
        # for details, see the signature of
        # novaclient.v<version>.servers.SeverManager.create()

        LOG.debug(_('device %s'), device)
        # flavor and image are specially treated by novaclient
        attributes = device['device_template']['attributes'].copy()
        attributes.update(device['kwargs'])

        name = self._safe_pop(attributes, ('name', ))
        if name is None:
            # TODO(yamahata): appropreate way to generate instance name
            name = (__name__ + ':' + self.__class__.__name__ + '-' +
                    device['id'])
        image = self._safe_pop(attributes, ('image', 'imageRef'))
        flavor = self._safe_pop(attributes, ('flavor', 'flavorRef'))

        files = plugin.mgmt_get_config(context, device)
        if files:
            attributes[_FILES] = files

        LOG.debug(_('service_context: %s'), device.get('service_context', []))
        tenant_id = device['tenant_id']
        nics = []
        for sc_entry in device.get('service_context', []):
            LOG.debug(_('sc_entry: %s'), sc_entry)

            # nova API doesn't return tacker port_id.
            # so create port if necessary by hand, and use it explicitly.
            if sc_entry['port_id']:
                LOG.debug(_('port_id %s specified'), sc_entry['port_id'])
                port_id = sc_entry['port_id']
            elif sc_entry['subnet_id']:
                LOG.debug(_('subnet_id %s specified'), sc_entry['subnet_id'])
                port_id = self._create_port(plugin, context, tenant_id,
                                            subnet_id=sc_entry['subnet_id'])
            elif sc_entry['network_id']:
                LOG.debug(_('network_id %s specified'), sc_entry['network_id'])
                port_id = self._create_port(plugin, context, tenant_id,
                                            network_id=sc_entry['network_id'])
            else:
                LOG.debug(_('skipping sc_entry %s'), sc_entry)
                continue

            LOG.debug(_('port_id %s'), port_id)
            port = plugin._core_plugin.get_port(context, port_id)
            sc_entry['network_id'] = port['network_id']
            if not sc_entry['subnet_id'] and port['fixed_ips']:
                sc_entry['subnet_id'] = port['fixed_ips'][0]['subnet_id']
            sc_entry['port_id'] = port_id

            nics.append({_PORT_ID: port_id})

        if nics:
            attributes[_NICS] = nics
        LOG.debug(_('nics %(nics)s attributes %(attributes)s'),
                  {'nics': nics, 'attributes': attributes})

        nova = self._nova_client()
        instance = nova.servers.create(name, image, flavor, **attributes)
        return instance.id

    def create_wait(self, plugin, context, device_id):
        nova = self._nova_client()
        instance = nova.servers.get(device_id)
        status = instance.status
        # TODO(yamahata): timeout and error
        while status == 'BUILD':
            time.sleep(5)
            instance = nova.servers.get(instance.id)
            status = instance.status
            LOG.debug(_('status: %s'), status)

        LOG.debug(_('status: %s'), status)
        if status == 'ERROR':
            raise RuntimeError(_("creation of server %s faild") % device_id)

    def update(self, plugin, context, device):
        # do nothing but checking if the instance exists at the moment
        device_id = device['id']
        nova = self._nova_client()
        nova.servers.get(device_id)

    def update_wait(self, plugin, context, device_id):
        # do nothing but checking if the instance exists at the moment
        nova = self._nova_client()
        nova.servers.get(device_id)

    def delete(self, plugin, context, device_id):
        nova = self._nova_client()
        instance = nova.servers.get(device_id)
        instance.delete()

    def delete_wait(self, plugin, context, device_id):
        nova = self._nova_client()
        # TODO(yamahata): timeout and error
        while True:
            try:
                instance = nova.servers.get(device_id)
                LOG.debug(_('instance status %s'), instance.status)
            except self._novaclient.exceptions.NotFound:
                break
            if instance.status == 'ERROR':
                raise RuntimeError(_("deletion of server %s faild") %
                                   device_id)
            time.sleep(5)
