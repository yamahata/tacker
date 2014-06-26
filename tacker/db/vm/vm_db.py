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

import uuid

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.orm import exc as orm_exc

from tacker.api.v1 import attributes
from tacker.db import api as qdbapi
from tacker.db import db_base
from tacker.db import model_base
from tacker.db import models_v1
from tacker.extensions import servicevm
from tacker import manager
from tacker.openstack.common import jsonutils
from tacker.openstack.common import log as logging
from tacker.plugins.common import constants

LOG = logging.getLogger(__name__)
_ACTIVE_UPDATE = (constants.ACTIVE, constants.PENDING_UPDATE)


###########################################################################
# db tables

# This table corresponds to SeviceVM of the origial spec of Blueprint
# https://docs.google.com/document/d/
# 1pwFVV8UavvQkBz92bT-BweBAiIZoMJP0NPAO4-60XFY/edit?pli=1
class DeviceTemplate(model_base.BASE, models_v1.HasId, models_v1.HasTenant):
    """Represents template to create hosting device
    """
    # Descriptive name
    name = sa.Column(sa.String(255))
    description = sa.Column(sa.String(255))

    # service type that this service vm provides.
    # At first phase, this includes only single service
    # In future, single service VM may accomodate multiple services.
    service_types = orm.relationship('ServiceType', backref='template')

    # driver to create hosting device. e.g. noop, nova, heat, etc...
    device_driver = sa.Column(sa.String(255))

    # mgmt driver to communicate with hosting device.
    # e.g. noop, OpenStack MGMT, OpenStack notification, netconf, snmp,
    #      ssh, etc...
    mgmt_driver = sa.Column(sa.String(255))

    # (key, value) pair to spin up
    attributes = orm.relationship('DeviceTemplateAttribute',
                                  backref='template')

    # TODO(yamahata): re-think the necessity of following columns
    #                 They are all commented out for minimalism for now.
    #                 They will be added when it is found really necessary.
    #
    # the name of the interface inside the VM
    # For agent in hosting device
    # (or something responsible for it in hosting device) to recieve
    # requests from management tools
    # vm_mgmt_if = sa.Column(sa.String(255), default='eth0')
    #
    # security_group = sa.Column(sa.String(36))
    # multi_tenant = sa.Column(sa.Boolean(), default=False)
    #
    # max_lsi = sa.Column(sa.Integer, default=0)
    # dp_if_types = sa.Column(sa.String(255))
    #
    # classification = sa.Column(sa.String(255), nullable=True)
    # availability_zone = sa.Column(sa.String(36), nullable=True)
    # host_aggregate = sa.Column(sa.String(36), nullable=True)
    # allow_mgmt_access = sa.Column(sa.Boolean(), default=False)
    # access_cred_uname = sa.Column(sa.String(255), nullable=True)
    # access_cred_passwd = sa.Column(sa.String(255), nullable=True)


# this table corresponds to Service_Type in ServiceVM of the original spec
# TODO(yamahata): reach consensus for naming.
#                 'service' might be too generic terminology.
class ServiceType(model_base.BASE, models_v1.HasId, models_v1.HasTenant):
    """Represents service type which hosting device provides.
    Since a device may provide many services, This is one-to-many
    relationship.
    """
    template_id = sa.Column(sa.String(36), sa.ForeignKey('devicetemplates.id'),
                            nullable=False)
    service_type = sa.Column(sa.String(255), nullable=False)


# this table corresponds to image, flavor in ServiceVM of the original spec
# Or just string long enough?
class DeviceTemplateAttribute(model_base.BASE, models_v1.HasId):
    """Represents attributes necessary for spinning up VM in (key, value) pair
    key value pair is adopted for being agnostic to actuall manager of VMs
    like nova, heat or others. e.g. image-id, flavor-id for Nova.
    The interpretation is up to actual driver of hosting device.
    """
    template_id = sa.Column(sa.String(36), sa.ForeignKey('devicetemplates.id'),
                            nullable=False)
    key = sa.Column(sa.String(255), nullable=False)
    value = sa.Column(sa.String(255), nullable=True)


class Device(model_base.BASE, models_v1.HasId, models_v1.HasTenant):
    """Represents devices that hosts services.
    Here the term, 'VM', is intentionally avoided because it can be
    VM or other container.
    """
    template_id = sa.Column(sa.String(36), sa.ForeignKey('devicetemplates.id'))
    template = orm.relationship('DeviceTemplate')

    # sufficient information to uniquely identify hosting device.
    # In case of service VM, it's UUID of nova VM.
    instance_id = sa.Column(sa.String(255), nullable=True)

    # For a management tool to talk to manage this hosting device.
    # opaque string. mgmt_driver interprets it.
    # e.g. (driver, mgmt_address) = (ssh, ip address), ...
    mgmt_address = sa.Column(sa.String(255), nullable=True)

    service_context = orm.relationship('DeviceServiceContext')
    services = orm.relationship('ServiceDeviceBinding', backref='device')

    status = sa.Column(sa.String(255), nullable=False)


class DeviceArg(model_base.BASE, models_v1.HasId):
    """Represents kwargs necessary for spinning up VM in (key, value) pair
    key value pair is adopted for being agnostic to actuall manager of VMs
    like nova, heat or others. e.g. image-id, flavor-id for Nova.
    The interpretation is up to actual driver of hosting device.
    """
    device_id = sa.Column(sa.String(36), sa.ForeignKey('devices.id'),
                          nullable=False)
    device = orm.relationship('Device', backref='kwargs')
    key = sa.Column(sa.String(255), nullable=False)
    # json encoded value. example
    # "nic": [{"net-id": <net-uuid>}, {"port-id": <port-uuid>}]
    value = sa.Column(sa.String(4096), nullable=True)


# TODO(yamahata): This is tentative.
#                 In the future, this will be replaced with db models of
#                 service insertion/chain.
#                 Since such models are under discussion/development as of
#                 this time, this models is just for lbaas driver of hosting
#                 device
# This corresponds to the instantiation of DP_IF_Types
class DeviceServiceContext(model_base.BASE, models_v1.HasId):
    """Represents service context of Device for scheduler.
    This represents service insertion/chainging of a given device.
    """
    device_id = sa.Column(sa.String(36), sa.ForeignKey('devices.id'))
    network_id = sa.Column(sa.String(36), nullable=True)
    subnet_id = sa.Column(sa.String(36), nullable=True)
    port_id = sa.Column(sa.String(36), nullable=True)
    router_id = sa.Column(sa.String(36), nullable=True)

    role = sa.Column(sa.String(255), nullable=True)
    # disambiguation between same roles
    index = sa.Column(sa.Integer, nullable=True)


# this table corresponds to ServiceInstance of the original spec
class ServiceInstance(model_base.BASE, models_v1.HasId, models_v1.HasTenant):
    """Represents logical service instance
    This table is only to tell what logical service instances exists.
    There will be service specific tables for each service types which holds
    actuall parameters necessary for specific service type.
    For example, tables for "Routers", "LBaaS", "FW", tables. which table
    is implicitly determined by service_type_id.
    """
    name = sa.Column(sa.String(255), nullable=True)
    service_type_id = sa.Column(sa.String(36),
                                sa.ForeignKey('servicetypes.id'))
    service_type = orm.relationship('ServiceType')
    # points to row in service specific table if any.
    service_table_id = sa.Column(sa.String(36), nullable=True)

    # True: This service is managed by user so that user is able to
    #       change its configurations
    # False: This service is manged by other tacker service like lbaas
    #        so that user can't change the configuration directly via
    #        servicevm API, but via API for the service.
    managed_by_user = sa.Column(sa.Boolean(), default=False)

    # mgmt driver to communicate with logical service instance in
    # hosting device.
    # e.g. noop, OpenStack MGMT, OpenStack notification, netconf, snmp,
    #      ssh, etc...
    mgmt_driver = sa.Column(sa.String(255))

    # For a management tool to talk to manage this service instance.
    # opaque string. mgmt_driver interprets it.
    mgmt_address = sa.Column(sa.String(255), nullable=True)

    service_context = orm.relationship('ServiceContext')
    devices = orm.relationship('ServiceDeviceBinding')

    status = sa.Column(sa.String(255), nullable=False)

    # TODO(yamahata): re-think the necessity of following columns
    #                 They are all commented out for minimalism for now.
    #                 They will be added when it is found really necessary.
    #
    # multi_tenant = sa.Column(sa.Boolean())
    # state = sa.Column(sa.Enum('UP', 'DOWN',
    #                           name='service_instance_state'))
    # For a logical service instance in hosting device to recieve
    # requests from management tools.
    # opaque string. mgmt_driver interprets it.
    # e.g. the name of the interface inside the VM + protocol
    # vm_mgmt_if = sa.Column(sa.String(255), default=None, nullable=True)
    # networks =
    # obj_store =
    # cost_factor =


# TODO(yamahata): This is tentative.
#                 In the future, this will be replaced with db models of
#                 service insertion/chain.
#                 Since such models are under discussion/development as of
#                 this time, this models is just for lbaas driver of hosting
#                 device
# This corresponds to networks of Logical Service Instance in the origianl spec
class ServiceContext(model_base.BASE, models_v1.HasId):
    """Represents service context of logical service instance.
    This represents service insertion/chainging of a given device.
    This is equal or subset of DeviceServiceContext of the
    corresponding Device.
    """
    service_instance_id = sa.Column(sa.String(36),
                                    sa.ForeignKey('serviceinstances.id'))
    network_id = sa.Column(sa.String(36), nullable=True)
    subnet_id = sa.Column(sa.String(36), nullable=True)
    port_id = sa.Column(sa.String(36), nullable=True)
    router_id = sa.Column(sa.String(36), nullable=True)

    role = sa.Column(sa.String(255), nullable=True)
    index = sa.Column(sa.Integer, nullable=True)        # disambiguation


class ServiceDeviceBinding(model_base.BASE):
    """Represents binding with Device and LogicalResource.
    Since Device can accomodate multiple services, it's many-to-one
    relationship.
    """
    service_instance_id = sa.Column(
        sa.String(36), sa.ForeignKey('serviceinstances.id'), primary_key=True)
    device_id = sa.Column(sa.String(36), sa.ForeignKey('devices.id'),
                          primary_key=True)


###########################################################################
# actual code to manage those tables
class ServiceContextEntry(dict):
    @classmethod
    def create(cls, network_id, subnet_id, port_id, router_id, role, index):
        return cls({
            'network_id': network_id,
            'subnet_id': subnet_id,
            'port_id': port_id,
            'router_id': router_id,
            'role': role,
            'index': index,
        })


class ServiceResourcePluginDb(servicevm.ServiceVMPluginBase,
                              db_base.CommonDbMixin):

    @property
    def _core_plugin(self):
        return manager.TackerManager.get_plugin()

    def subnet_id_to_network_id(self, context, subnet_id):
        subnet = self._core_plugin.get_subnet(context, subnet_id)
        return subnet['network_id']

    def __init__(self):
        qdbapi.register_models()
        super(ServiceResourcePluginDb, self).__init__()

    def _get_resource(self, context, model, id):
        try:
            return self._get_by_id(context, model, id)
        except orm_exc.NoResultFound:
            if issubclass(model, DeviceTemplate):
                raise servicevm.DeviceTemplateNotFound(device_tempalte_id=id)
            elif issubclass(model, ServiceType):
                raise servicevm.ServiceTypeNotFound(service_type_id=id)
            elif issubclass(model, ServiceInstance):
                raise servicevm.ServiceInstanceNotFound(service_instance_id=id)
            if issubclass(model, Device):
                raise servicevm.DeviceNotFound(device_id=id)
            else:
                raise

    def _make_attributes_dict(self, attributes_db):
        return dict((attr.key, attr.value) for attr in attributes_db)

    def _make_service_types_list(self, service_types):
        return [{'id': service_type.id,
                 'service_type': service_type.service_type}
                for service_type in service_types]

    def _make_template_dict(self, template, fields=None):
        res = {
            'attributes': self._make_attributes_dict(template['attributes']),
            'service_types':
            self._make_service_types_list(template['service_types']),
        }
        key_list = ('id', 'tenant_id', 'name', 'description',
                    'device_driver', 'mgmt_driver')
        res.update((key, template[key]) for key in key_list)
        return self._fields(res, fields)

    def _make_services_list(self, binding_db):
        return [binding.service_instance_id for binding in binding_db]

    def _make_kwargs_dict(self, kwargs_db):
        return dict((arg.key, jsonutils.loads(arg.value)) for arg in kwargs_db)

    def _make_device_service_context_dict(self, service_context):
        key_list = ('id', 'network_id', 'subnet_id', 'port_id', 'router_id',
                    'role', 'index')
        return [self._fields(dict((key, entry[key]) for key in key_list), None)
                for entry in service_context]

    def _make_device_dict(self, device_db, fields=None):
        LOG.debug(_('device_db %s'), device_db)
        res = {
            'services':
            self._make_services_list(getattr(device_db, 'services', [])),
            'device_template':
            self._make_template_dict(device_db.template),
            'kwargs': self._make_kwargs_dict(device_db.kwargs),
            'service_context':
            self._make_device_service_context_dict(device_db.service_context),
        }
        key_list = ('id', 'tenant_id', 'instance_id', 'template_id', 'status',
                    'mgmt_address')
        res.update((key, device_db[key]) for key in key_list)
        return self._fields(res, fields)

    def _make_service_context_dict(self, service_context):
        key_list = ('id', 'network_id', 'subnet_id', 'port_id', 'router_id',
                    'role', 'index')
        return [self._fields(dict((key, entry[key]) for key in key_list), None)
                for entry in service_context]

    def _make_service_device_list(self, devices):
        return [binding.device_id for binding in devices]

    def _make_service_instance_dict(self, instance_db, fields=None):
        res = {
            'service_context':
            self._make_service_context_dict(instance_db.service_context),
            'devices':
            self._make_service_device_list(instance_db.devices)
        }
        key_list = ('id', 'tenant_id', 'name', 'service_type_id',
                    'service_table_id', 'mgmt_driver', 'mgmt_address',
                    'status')
        res.update((key, instance_db[key]) for key in key_list)
        return self._fields(res, fields)

    @staticmethod
    def _device_driver_name(device_dict):
        return device_dict['device_template']['device_driver']

    @staticmethod
    def _mgmt_device_driver(device_dict):
        return device_dict['device_template']['mgmt_driver']

    @staticmethod
    def _mgmt_service_driver(service_instance_dict):
        return service_instance_dict['mgmt_driver']

    @staticmethod
    def _instance_id(device_dict):
        return device_dict['instance_id']

    ###########################################################################
    # hosting device template

    def create_device_template(self, context, device_template):
        template = device_template['device_template']
        LOG.debug(_('template %s'), template)
        tenant_id = self._get_tenant_id_for_create(context, template)
        device_driver = template.get('device_driver')
        mgmt_driver = template.get('mgmt_driver')
        service_types = template.get('service_types')

        if (not attributes.is_attr_set(device_driver)):
            LOG.debug(_('hosting device driver unspecified'))
            raise servicevm.DeviceDriverNotSpecified()
        if (not attributes.is_attr_set(mgmt_driver)):
            LOG.debug(_('mgmt driver unspecified'))
            raise servicevm.MGMTDriverNotSpecified()
        if (not attributes.is_attr_set(service_types)):
            LOG.debug(_('service types unspecified'))
            raise servicevm.SeviceTypesNotSpecified()

        with context.session.begin(subtransactions=True):
            template_id = str(uuid.uuid4())
            template_db = DeviceTemplate(
                id=template_id,
                tenant_id=tenant_id,
                name=template.get('name'),
                description=template.get('description'),
                device_driver=device_driver,
                mgmt_driver=mgmt_driver)
            context.session.add(template_db)
            for (key, value) in template.get('attributes', {}).items():
                attribute_db = DeviceTemplateAttribute(
                    id=str(uuid.uuid4()),
                    template_id=template_id,
                    key=key,
                    value=value)
                context.session.add(attribute_db)
            for service_type in (item['service_type']
                                 for item in template['service_types']):
                service_type_db = ServiceType(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    template_id=template_id,
                    service_type=service_type)
                context.session.add(service_type_db)

        LOG.debug(_('template_db %(template_db)s %(attributes)s '
                    '%(service_types)s'),
                  {'template_db': template_db,
                   'attributes': template_db.attributes,
                   'service_types': template_db.service_types})
        return self._make_template_dict(template_db)

    def update_device_template(self, context, device_template_id,
                               device_template):
        with context.session.begin(subtransactions=True):
            template_db = self._get_resource(context, DeviceTemplate,
                                             device_template_id)
            template_db.update(device_template['device_template'])
        return self._make_template_dict(template_db)

    def delete_device_template(self, context, device_template_id):
        with context.session.begin(subtransactions=True):
            # TODO(yamahata): race. prevent from newly inserting hosting device
            #                 that refers to this template
            devices_db = context.session.query(Device).filter_by(
                template_id=device_template_id).first()
            if devices_db is not None:
                raise servicevm.DeviceTemplateInUse(
                    device_template_id=device_template_id)

            context.session.query(ServiceType).filter_by(
                template_id=device_template_id).delete()
            context.session.query(DeviceTemplateAttribute).filter_by(
                template_id=device_template_id).delete()
            template_db = self._get_resource(context, DeviceTemplate,
                                             device_template_id)
            context.session.delete(template_db)

    def get_device_template(self, context, device_template_id, fields=None):
        template_db = self._get_resource(context, DeviceTemplate,
                                         device_template_id)
        return self._make_template_dict(template_db)

    def get_device_templates(self, context, filters, fields=None):
        return self._get_collection(context, DeviceTemplate,
                                    self._make_template_dict,
                                    filters=filters, fields=fields)

    # called internally, not by REST API
    # need enhancement?
    def choose_device_template(self, context, service_type,
                               required_attributes=None):
        required_attributes = required_attributes or []
        LOG.debug(_('required_attributes %s'), required_attributes)
        with context.session.begin(subtransactions=True):
            query = (
                context.session.query(DeviceTemplate).
                filter(
                    sa.exists().
                    where(sa.and_(
                        DeviceTemplate.id == ServiceType.template_id,
                        ServiceType.service_type == service_type))))
            for key in required_attributes:
                query = query.filter(
                    sa.exists().
                    where(sa.and_(
                        DeviceTemplate.id ==
                        DeviceTemplateAttribute.template_id,
                        DeviceTemplateAttribute.key == key)))
            LOG.debug(_('statements %s'), query)
            template_db = query.first()
            if template_db:
                return self._make_template_dict(template_db)

    ###########################################################################
    # hosting device

    # called internally, not by REST API
    def _create_device_pre(self, context, device):
        device = device['device']
        LOG.debug(_('device %s'), device)
        tenant_id = self._get_tenant_id_for_create(context, device)
        template_id = device['template_id']
        device_id = str(uuid.uuid4())
        kwargs = device.get('kwargs', {})
        service_context = device.get('service_context', [])
        with context.session.begin(subtransactions=True):
            device_db = Device(id=device_id,
                               tenant_id=tenant_id,
                               instance_id=None,
                               template_id=template_id,
                               status=constants.PENDING_CREATE)
            context.session.add(device_db)
            for key, value in kwargs.items():
                arg = DeviceArg(id=str(uuid.uuid4()), device_id=device_id,
                                key=key, value=jsonutils.dumps(value))
                context.session.add(arg)

            LOG.debug(_('service_context %s'), service_context)
            for sc_entry in service_context:
                LOG.debug(_('sc_entry %s'), sc_entry)
                network_id = sc_entry.get('network_id')
                subnet_id = sc_entry.get('subnet_id')
                port_id = sc_entry.get('port_id')
                router_id = sc_entry.get('router_id')
                role = sc_entry.get('role')
                index = sc_entry.get('index')
                network_binding = DeviceServiceContext(
                    id=str(uuid.uuid4()), device_id=device_id,
                    network_id=network_id, subnet_id=subnet_id,
                    port_id=port_id, router_id=router_id, role=role,
                    index=index)
                context.session.add(network_binding)

        return self._make_device_dict(device_db)

    # called internally, not by REST API
    # intsance_id = None means error on creation
    def _create_device_post(self, context, device_id, instance_id,
                            mgmt_address, service_context):
        with context.session.begin(subtransactions=True):
            query = (self._model_query(context, Device).
                     filter(Device.id == device_id).
                     filter(Device.status == constants.PENDING_CREATE).
                     one())
            query.update({'instance_id': instance_id,
                          'mgmt_address': mgmt_address})
            if instance_id is None:
                query.update({'status': constants.ERROR})

            for sc_entry in service_context:
                # some member of service context is determined during
                # creating hosting device.
                (self._model_query(context, DeviceServiceContext).
                    filter(DeviceServiceContext.id == sc_entry['id']).
                    update({'network_id': sc_entry['network_id'],
                            'subnet_id': sc_entry['subnet_id'],
                            'port_id': sc_entry['port_id'],
                            'router_id': sc_entry['router_id'],
                            'role': sc_entry['role'],
                            'index': sc_entry['index']}))

    def _create_device_status(self, context, device_id, new_status):
        with context.session.begin(subtransactions=True):
            (self._model_query(context, Device).
                filter(Device.id == device_id).
                filter(Device.status == constants.PENDING_CREATE).
                update({'status': new_status}))

    def _get_device_db(self, context, device_id, new_status):
        try:
            device_db = (
                self._model_query(context, Device).
                filter(Device.id == device_id).
                filter(Device.status.in_(_ACTIVE_UPDATE)).
                filter(Device.status == constants.ACTIVE).
                with_lockmode('update').one())
        except orm_exc.NoResultFound:
            raise servicevm.DeviceNotFound(device_id=device_id)
        if device_db.status == constants.PENDING_UPDATE:
            raise servicevm.DeviceInUse(device_id=device_id)
        device_db.update({'status': new_status})
        return device_db

    def _update_device_pre(self, context, device_id):
        with context.session.begin(subtransactions=True):
            device_db = self._get_device_db(context, device_id,
                                            constants.PENDING_UPDATE)
        return self._make_device_dict(device_db)

    def _update_device_post(self, context, device_id, new_status):
        with context.session.begin(subtransactions=True):
            (self._model_query(context, Device).
             filter(Device.id == device_id).
             filter(Device.status == constants.PENDING_UPDATE).
             update({'status': new_status}))

    def _delete_device_pre(self, context, device_id):
        with context.session.begin(subtransactions=True):
            # TODO(yamahata): race. keep others from inserting new binding
            binding_db = (context.session.query(ServiceDeviceBinding).
                          filter_by(device_id=device_id).first())
            if binding_db is not None:
                raise servicevm.DeviceInUse(device_id=device_id)
            device_db = self._get_device_db(context, device_id,
                                            constants.PENDING_DELETE)

        return self._make_device_dict(device_db)

    def _delete_device_post(self, context, device_id, error):
        with context.session.begin(subtransactions=True):
            query = (
                self._model_query(context, Device).
                filter(Device.id == device_id).
                filter(Device.status == constants.PENDING_DELETE))
            if error:
                query.update({'status': constants.ERROR})
            else:
                (self._model_query(context, DeviceArg).
                 filter(DeviceArg.device_id == device_id).delete())
                (self._model_query(context, DeviceServiceContext).
                 filter(DeviceServiceContext.device_id == device_id).delete())
                query.delete()

    # reference implementation. needs to be overrided by subclass
    def create_device(self, context, device):
        device_dict = self._create_device_pre(context, device)
        # start actual creation of hosting device.
        # Waiting for completion of creation should be done backgroundly
        # by another thread if it takes a while.
        instance_id = str(uuid.uuid4())
        device_dict['instance_id'] = instance_id
        self._create_device_post(context, device_dict['id'], instance_id, None,
                                 device_dict['service_context'])
        self._create_device_status(context, device_dict['id'],
                                   constants.ACTIVE)
        return device_dict

    # reference implementation. needs to be overrided by subclass
    def update_device(self, context, device_id, device):
        device_dict = self._update_device_pre(context, device_id)
        # start actual update of hosting device
        # waiting for completion of update should be done backgroundly
        # by another thread if it takes a while
        self._update_device_post(context, device_id, constants.ACTIVE)
        return device_dict

    # reference implementation. needs to be overrided by subclass
    def delete_device(self, context, device_id):
        self._delete_device_pre(context, device_id)
        # start actual deletion of hosting device.
        # Waiting for completion of deletion should be done backgroundly
        # by another thread if it takes a while.
        self._delete_device_post(context, device_id, False)

    def get_device(self, context, device_id, fields=None):
        device_db = self._get_resource(context, Device, device_id)
        return self._make_device_dict(device_db, fields)

    def get_devices(self, context, filters=None, fields=None):
        return self._get_collection(context, Device, self._make_device_dict,
                                    filters=filters, fields=fields)

    ###########################################################################
    # logical service instance

    # called internally, not by REST API
    def _create_service_instance(self, context, device_id,
                                 service_instance_param, managed_by_user):
        """
        :param service_instance_param: dictionary to create
            instance of ServiceInstance. The following keys are used.
            name, service_type_id, service_table_id, mgmt_driver, mgmt_address
        mgmt_driver, mgmt_address can be determined later.
        """
        name = service_instance_param['name']
        service_type_id = service_instance_param['service_type_id']
        service_table_id = service_instance_param['service_table_id']
        mgmt_driver = service_instance_param.get('mgmt_driver')
        mgmt_address = service_instance_param.get('mgmt_address')

        service_instance_id = str(uuid.uuid4())
        LOG.debug('service_instance_id %s device_id %s',
                  service_instance_id, device_id)
        with context.session.begin(subtransactions=True):
            # TODO(yamahata): race. prevent modifying/deleting service_type
            # with_lockmode("update")
            device_db = self._get_resource(context, Device, device_id)
            device_dict = self._make_device_dict(device_db)
            tenant_id = self._get_tenant_id_for_create(context, device_dict)
            instance_db = ServiceInstance(
                id=service_instance_id,
                tenant_id=tenant_id,
                name=name,
                service_type_id=service_type_id,
                service_table_id=service_table_id,
                managed_by_user=managed_by_user,
                status=constants.PENDING_CREATE,
                mgmt_driver=mgmt_driver,
                mgmt_address=mgmt_address)
            context.session.add(instance_db)
            context.session.flush()

            binding_db = ServiceDeviceBinding(
                service_instance_id=service_instance_id, device_id=device_id)
            context.session.add(binding_db)

        return self._make_service_instance_dict(instance_db)

    # reference implementation. must be overriden by subclass
    def create_service_instance(self, context, service_instance):
        self._create_service_instance(
            context, service_instance['service_instance'], True)

    def _update_service_instance_mgmt(self, context, service_instance_id,
                                      mgmt_driver, mgmt_address):
        with context.session.begin(subtransactions=True):
            (self._model_query(context, ServiceInstance).
             filter(ServiceInstance.id == service_instance_id).
             filter(ServiceInstance.status == constants.PENDING_CREATE).
             one().
             update({'mgmt_driver': mgmt_driver,
                     'mgmt_address': mgmt_address}))

    def _update_service_instance_pre(self, context, service_instance_id,
                                     service_instance):
        with context.session.begin(subtransactions=True):
            instance_db = (
                self._model_query(context, ServiceInstance).
                filter(ServiceInstance.id == service_instance_id).
                filter(Device.status == constants.ACTIVE).
                with_lockmode('update').one())
            instance_db.update(service_instance)
            instance_db.update({'status': constants.PENDING_UPDATE})
        return self._make_service_instance_dict(instance_db)

    def _update_service_instance_post(self, context, service_instance_id,
                                      status):
        with context.session.begin(subtransactions=True):
            (self._model_query(context, ServiceInstance).
             filter(ServiceInstance.id == service_instance_id).
             filter(ServiceInstance.status.in_(
                 [constants.PENDING_CREATE, constants.PENDING_UPDATE])).one().
             update({'status': status}))

    # reference implementation
    def update_service_instance(self, context, service_instance_id,
                                service_instance):
        service_instance_dict = self._update_service_instance_pre(
            context, service_instance_id, service_instance)
        self._update_service_instance_post(
            context, service_instance_id, service_instance, constants.ACTIVE)
        return service_instance_dict

    def _delete_service_instance_pre(self, context, service_instance_id,
                                     managed_by_user):
        with context.session.begin(subtransactions=True):
            service_instance = (
                self._model_query(context, ServiceInstance).
                filter(ServiceInstance.id == service_instance_id).
                filter(ServiceInstance.status == constants.ACTIVE).
                with_lockmode('update').one())

            if service_instance.managed_by_user != managed_by_user:
                raise servicevm.ServiceInstanceNotManagedByUser(
                    service_instance_id=service_instance_id)

            service_instance.status = constants.PENDING_DELETE

            binding_db = (
                self._model_query(context, ServiceDeviceBinding).
                filter(ServiceDeviceBinding.service_instance_id ==
                       service_instance_id).
                all())
            assert binding_db
            # check only. _post method will delete it.
            if len(binding_db) > 1:
                raise servicevm.ServiceInstanceInUse(
                    service_instance_id=service_instance_id)

    def _delete_service_instance_post(self, context, service_instance_id):
        with context.session.begin(subtransactions=True):
            binding_db = (
                self._model_query(context, ServiceDeviceBinding).
                filter(ServiceDeviceBinding. service_instance_id ==
                       service_instance_id).
                all())
            assert binding_db
            assert len(binding_db) == 1
            context.session.delete(binding_db[0])

            (self._model_query(context, ServiceInstance).
             filter(ServiceInstance.id == service_instance_id).
             filter(ServiceInstance.status == constants.PENDING_DELETE).
             delete())

    # reference implementation. needs to be overriden by subclass
    def _delete_service_instance(self, context, service_instance_id,
                                 managed_by_user):
        self._delete_service_instance_pre(context, service_instance_id,
                                          managed_by_user)
        self._delete_service_instance_post(context, service_instance_id)

    # reference implementation. needs to be overriden by subclass
    def delete_service_instance(self, context, service_instance_id):
        self._delete_service_instance(context, service_instance_id, True)

    def get_by_service_table_id(self, context, service_table_id):
        with context.session.begin(subtransactions=True):
            instance_db = (self._model_query(context, ServiceInstance).
                           filter(ServiceInstance.service_table_id ==
                                  service_table_id).one())
            device_db = (
                self._model_query(context, Device).
                filter(sa.exists().where(sa.and_(
                    ServiceDeviceBinding.device_id == Device.id,
                    ServiceDeviceBinding.service_instance_id ==
                    instance_db.id))).one())
        return (self._make_device_dict(device_db),
                self._make_service_instance_dict(instance_db))

    def get_by_service_instance_id(self, context, service_instance_id):
        with context.session.begin(subtransactions=True):
            instance_db = self._get_resource(context, ServiceInstance,
                                             service_instance_id)
            device_db = (
                self._model_query(context, Device).
                filter(sa.exists().where(sa.and_(
                    ServiceDeviceBinding.device_id == Device.id,
                    ServiceDeviceBinding.service_instance_id ==
                    instance_db.id))).one())
        return (self._make_device_dict(device_db),
                self._make_service_instance_dict(instance_db))

    def get_service_instance(self, context, service_instance_id, fields=None):
        instance_db = self._get_resource(context, ServiceInstance,
                                         service_instance_id)
        return self._make_service_instance_dict(instance_db, fields)

    def get_service_instances(self, context, filters=None, fields=None):
        return self._get_collection(
            context, ServiceInstance, self._make_service_instance_dict,
            filters=filters, fields=fields)
