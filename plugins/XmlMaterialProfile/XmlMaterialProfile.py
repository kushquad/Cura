# Copyright (c) 2016 Ultimaker B.V.
# Cura is released under the terms of the AGPLv3 or higher.

import math
import copy
import io
import xml.etree.ElementTree as ET
import uuid

from UM.Logger import Logger

import UM.Dictionary

import UM.Settings

##  Handles serializing and deserializing material containers from an XML file
class XmlMaterialProfile(UM.Settings.InstanceContainer):
    def __init__(self, container_id, *args, **kwargs):
        super().__init__(container_id, *args, **kwargs)

    ##  Overridden from InstanceContainer
    def duplicate(self, new_id, new_name = None):
        base_file = self.getMetaDataEntry("base_file", None)
        new_uuid = str(uuid.uuid4())

        if base_file:
            containers = UM.Settings.ContainerRegistry.getInstance().findInstanceContainers(id = base_file)
            if containers:
                new_basefile = containers[0].duplicate(self.getMetaDataEntry("brand") + "_" + new_id, new_name)
                new_basefile.setMetaDataEntry("GUID", new_uuid)
                base_file = new_basefile.id
                UM.Settings.ContainerRegistry.getInstance().addContainer(new_basefile)

                new_id = self.getMetaDataEntry("brand") + "_" + new_id + "_" + self.getDefinition().getId()
                variant = self.getMetaDataEntry("variant")
                if variant:
                    variant_containers = UM.Settings.ContainerRegistry.getInstance().findInstanceContainers(id = variant)
                    if variant_containers:
                        new_id += "_" + variant_containers[0].getName().replace(" ", "_")

        result = super().duplicate(new_id, new_name)
        result.setMetaDataEntry("GUID", new_uuid)
        if result.getMetaDataEntry("base_file", None):
            result.setMetaDataEntry("base_file", base_file)
        return result

    ##  Overridden from InstanceContainer
    def setReadOnly(self, read_only):
        super().setReadOnly(read_only)

        for container in UM.Settings.ContainerRegistry.getInstance().findInstanceContainers(GUID = self.getMetaDataEntry("GUID")):
            container._read_only = read_only

    ##  Overridden from InstanceContainer
    def setMetaDataEntry(self, key, value):
        if self.isReadOnly():
            return

        super().setMetaDataEntry(key, value)

        if key == "material":
            self.setName(value)

        for container in UM.Settings.ContainerRegistry.getInstance().findInstanceContainers(GUID = self.getMetaDataEntry("GUID")):
            container.setMetaData(copy.deepcopy(self._metadata))
            if key == "material":
                container.setName(value)

    ##  Overridden from InstanceContainer
    def setProperty(self, key, property_name, property_value, container = None):
        if self.isReadOnly():
            return

        super().setProperty(key, property_name, property_value)

        for container in UM.Settings.ContainerRegistry.getInstance().findInstanceContainers(GUID = self.getMetaDataEntry("GUID")):
            container._dirty = True

    ##  Overridden from InstanceContainer
    def serialize(self):
        registry = UM.Settings.ContainerRegistry.getInstance()

        base_file = self.getMetaDataEntry("base_file", "")
        if base_file and self.id != base_file:
            # Since we create an instance of XmlMaterialProfile for each machine and nozzle in the profile,
            # we should only serialize the "base" material definition, since that can then take care of
            # serializing the machine/nozzle specific profiles.
            raise NotImplementedError("Cannot serialize non-root XML materials")

        builder = ET.TreeBuilder()

        root = builder.start("fdmmaterial", { "xmlns": "http://www.ultimaker.com/material"})

        ## Begin Metadata Block
        builder.start("metadata")

        metadata = copy.deepcopy(self.getMetaData())
        properties = metadata.pop("properties", {})

        # Metadata properties that should not be serialized.
        metadata.pop("status", "")
        metadata.pop("variant", "")
        metadata.pop("type", "")
        metadata.pop("base_file", "")

        ## Begin Name Block
        builder.start("name")

        builder.start("brand")
        builder.data(metadata.pop("brand", ""))
        builder.end("brand")

        builder.start("material")
        builder.data(metadata.pop("material", ""))
        builder.end("material")

        builder.start("color")
        builder.data(metadata.pop("color_name", ""))
        builder.end("color")

        builder.end("name")
        ## End Name Block

        for key, value in metadata.items():
            builder.start(key)
            builder.data(value)
            builder.end(key)

        builder.end("metadata")
        ## End Metadata Block

        ## Begin Properties Block
        builder.start("properties")

        for key, value in properties.items():
            builder.start(key)
            builder.data(value)
            builder.end(key)

        builder.end("properties")
        ## End Properties Block

        ## Begin Settings Block
        builder.start("settings")

        if self.getDefinition().id == "fdmprinter":
            for instance in self.findInstances():
                self._addSettingElement(builder, instance)

        machine_container_map = {}
        machine_nozzle_map = {}

        all_containers = registry.findInstanceContainers(GUID = self.getMetaDataEntry("GUID"))
        for container in all_containers:
            definition_id = container.getDefinition().id
            if definition_id == "fdmprinter":
                continue

            if definition_id not in machine_container_map:
                machine_container_map[definition_id] = container

            if definition_id not in machine_nozzle_map:
                machine_nozzle_map[definition_id] = {}

            variant = container.getMetaDataEntry("variant")
            if variant:
                machine_nozzle_map[definition_id][variant] = container
                continue

            machine_container_map[definition_id] = container

        for definition_id, container in machine_container_map.items():
            definition = container.getDefinition()
            try:
                product = UM.Dictionary.findKey(self.__product_id_map, definition_id)
            except ValueError:
                continue

            builder.start("machine")
            builder.start("machine_identifier", { "manufacturer": definition.getMetaDataEntry("manufacturer", ""), "product":  product})
            builder.end("machine_identifier")

            for instance in container.findInstances():
                if self.getDefinition().id == "fdmprinter" and self.getInstance(instance.definition.key) and self.getProperty(instance.definition.key, "value") == instance.value:
                    # If the settings match that of the base profile, just skip since we inherit the base profile.
                    continue

                self._addSettingElement(builder, instance)

            # Find all hotend sub-profiles corresponding to this material and machine and add them to this profile.
            for hotend_id, hotend in machine_nozzle_map[definition_id].items():
                variant_containers = registry.findInstanceContainers(id = hotend.getMetaDataEntry("variant"))
                if not variant_containers:
                    continue

                builder.start("hotend", { "id": variant_containers[0].getName() })

                for instance in hotend.findInstances():
                    if container.getInstance(instance.definition.key) and container.getProperty(instance.definition.key, "value") == instance.value:
                        # If the settings match that of the machine profile, just skip since we inherit the machine profile.
                        continue

                    self._addSettingElement(builder, instance)

                builder.end("hotend")

            builder.end("machine")

        builder.end("settings")
        ## End Settings Block

        builder.end("fdmmaterial")

        root = builder.close()
        _indent(root)
        stream = io.StringIO()
        tree = ET.ElementTree(root)
        tree.write(stream, "unicode", True)

        return stream.getvalue()

    ##  Overridden from InstanceContainer
    def deserialize(self, serialized):
        data = ET.fromstring(serialized)

        self.addMetaDataEntry("type", "material")

        # TODO: Add material verfication
        self.addMetaDataEntry("status", "unknown")

        metadata = data.iterfind("./um:metadata/*", self.__namespaces)
        for entry in metadata:
            tag_name = _tag_without_namespace(entry)

            if tag_name == "name":
                brand = entry.find("./um:brand", self.__namespaces)
                material = entry.find("./um:material", self.__namespaces)
                color = entry.find("./um:color", self.__namespaces)

                self.setName(material.text)

                self.addMetaDataEntry("brand", brand.text)
                self.addMetaDataEntry("material", material.text)
                self.addMetaDataEntry("color_name", color.text)

                continue

            self.addMetaDataEntry(tag_name, entry.text)

        if not "description" in self.getMetaData():
            self.addMetaDataEntry("description", "")

        if not "adhesion_info" in self.getMetaData():
            self.addMetaDataEntry("adhesion_info", "")

        property_values = {}
        properties = data.iterfind("./um:properties/*", self.__namespaces)
        for entry in properties:
            tag_name = _tag_without_namespace(entry)
            property_values[tag_name] = entry.text

        diameter = float(property_values.get("diameter", 2.85)) # In mm
        density = float(property_values.get("density", 1.3)) # In g/cm3

        self.addMetaDataEntry("properties", property_values)

        self.setDefinition(UM.Settings.ContainerRegistry.getInstance().findDefinitionContainers(id = "fdmprinter")[0])

        global_setting_values = {}
        settings = data.iterfind("./um:settings/um:setting", self.__namespaces)
        for entry in settings:
            key = entry.get("key")
            if key in self.__material_property_setting_map:
                self.setProperty(self.__material_property_setting_map[key], "value", entry.text, self._definition)
                global_setting_values[self.__material_property_setting_map[key]] = entry.text
            else:
                Logger.log("d", "Unsupported material setting %s", key)

        self._dirty = False

        machines = data.iterfind("./um:settings/um:machine", self.__namespaces)
        for machine in machines:
            machine_setting_values = {}
            settings = machine.iterfind("./um:setting", self.__namespaces)
            for entry in settings:
                key = entry.get("key")
                if key in self.__material_property_setting_map:
                    machine_setting_values[self.__material_property_setting_map[key]] = entry.text
                else:
                    Logger.log("d", "Unsupported material setting %s", key)

            identifiers = machine.iterfind("./um:machine_identifier", self.__namespaces)
            for identifier in identifiers:
                machine_id = self.__product_id_map.get(identifier.get("product"), None)
                if machine_id is None:
                    Logger.log("w", "Cannot create material for unknown machine %s", machine_id)
                    continue

                definitions = UM.Settings.ContainerRegistry.getInstance().findDefinitionContainers(id = machine_id)
                if not definitions:
                    Logger.log("w", "No definition found for machine ID %s", machine_id)
                    continue

                definition = definitions[0]

                new_material = XmlMaterialProfile(self.id + "_" + machine_id)
                new_material.setName(self.getName())
                new_material.setMetaData(copy.deepcopy(self.getMetaData()))
                new_material.setDefinition(definition)
                new_material.addMetaDataEntry("base_file", self.id)

                for key, value in global_setting_values.items():
                    new_material.setProperty(key, "value", value, definition)

                for key, value in machine_setting_values.items():
                    new_material.setProperty(key, "value", value, definition)

                new_material._dirty = False

                UM.Settings.ContainerRegistry.getInstance().addContainer(new_material)

                hotends = machine.iterfind("./um:hotend", self.__namespaces)
                for hotend in hotends:
                    hotend_id = hotend.get("id")
                    if hotend_id is None:
                        continue

                    variant_containers = UM.Settings.ContainerRegistry.getInstance().findInstanceContainers(id = hotend_id)
                    if not variant_containers:
                        # It is not really properly defined what "ID" is so also search for variants by name.
                        variant_containers = UM.Settings.ContainerRegistry.getInstance().findInstanceContainers(definition = definition.id, name = hotend_id)

                    if not variant_containers:
                        Logger.log("d", "No variants found with ID or name %s for machine %s", hotend_id, definition.id)
                        continue

                    new_hotend_material = XmlMaterialProfile(self.id + "_" + machine_id + "_" + hotend_id.replace(" ", "_"))
                    new_hotend_material.setName(self.getName())
                    new_hotend_material.setMetaData(copy.deepcopy(self.getMetaData()))
                    new_hotend_material.setDefinition(definition)
                    new_hotend_material.addMetaDataEntry("base_file", self.id)

                    new_hotend_material.addMetaDataEntry("variant", variant_containers[0].id)

                    for key, value in global_setting_values.items():
                        new_hotend_material.setProperty(key, "value", value, definition)

                    for key, value in machine_setting_values.items():
                        new_hotend_material.setProperty(key, "value", value, definition)

                    settings = hotend.iterfind("./um:setting", self.__namespaces)
                    for entry in settings:
                        key = entry.get("key")
                        if key in self.__material_property_setting_map:
                            new_hotend_material.setProperty(self.__material_property_setting_map[key], "value", entry.text, definition)
                        else:
                            Logger.log("d", "Unsupported material setting %s", key)

                    new_hotend_material._dirty = False
                    UM.Settings.ContainerRegistry.getInstance().addContainer(new_hotend_material)

    def _addSettingElement(self, builder, instance):
        try:
            key = UM.Dictionary.findKey(self.__material_property_setting_map, instance.definition.key)
        except ValueError:
            return

        builder.start("setting", { "key": key })
        builder.data(str(instance.value))
        builder.end("setting")

    # Map XML file setting names to internal names
    __material_property_setting_map = {
        "print temperature": "material_print_temperature",
        "heated bed temperature": "material_bed_temperature",
        "standby temperature": "material_standby_temperature",
        "print cooling": "cool_fan_speed",
        "retraction amount": "retraction_amount",
        "retraction speed": "retraction_speed",
    }

    # Map XML file product names to internal ids
    # TODO: Move this to definition's metadata
    __product_id_map = {
        "Ultimaker2": "ultimaker2",
        "Ultimaker2+": "ultimaker2_plus",
        "Ultimaker2go": "ultimaker2_go",
        "Ultimaker2extended": "ultimaker2_extended",
        "Ultimaker2extended+": "ultimaker2_extended_plus",
        "Ultimaker Original": "ultimaker_original",
        "Ultimaker Original+": "ultimaker_original_plus"
    }

    # Map of recognised namespaces with a proper prefix.
    __namespaces = {
        "um": "http://www.ultimaker.com/material"
    }

##  Helper function for pretty-printing XML because ETree is stupid
def _indent(elem, level = 0):
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            _indent(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


# The namespace is prepended to the tag name but between {}.
# We are only interested in the actual tag name, so discard everything
# before the last }
def _tag_without_namespace(element):
    return element.tag[element.tag.rfind("}") + 1:]
