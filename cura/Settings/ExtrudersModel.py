# Copyright (c) 2016 Ultimaker B.V.
# Cura is released under the terms of the AGPLv3 or higher.

from PyQt5.QtCore import Qt, pyqtSignal, pyqtProperty

import UM.Qt.ListModel
import UM.Math.Color

from . import ExtruderManager

##  Model that holds extruders.
#
#   This model is designed for use by any list of extruders, but specifically
#   intended for drop-down lists of the current machine's extruders in place of
#   settings.
class ExtrudersModel(UM.Qt.ListModel.ListModel):
    # The ID of the container stack for the extruder.
    IdRole = Qt.UserRole + 1

    ##  Human-readable name of the extruder.
    NameRole = Qt.UserRole + 2

    ##  Colour of the material loaded in the extruder.
    ColourRole = Qt.UserRole + 3

    ##  Index of the extruder, which is also the value of the setting itself.
    #
    #   An index of 0 indicates the first extruder, an index of 1 the second
    #   one, and so on. This is the value that will be saved in instance
    #   containers.
    IndexRole = Qt.UserRole + 4

    ##  List of colours to display if there is no material or the material has no known
    #   colour.
    defaultColours = ["#ffc924", "#86ec21", "#22eeee", "#245bff", "#9124ff", "#ff24c8"]

    ##  Amount by which the material colour is shaded for the last extruder.
    #
    #   The first extruder gets the pure colour, the other extruders are gradually made
    #   darker or lighter depending on the brightness of the pure colour.
    shadeAmount = 0.4

    ##  Initialises the extruders model, defining the roles and listening for
    #   changes in the data.
    #
    #   \param parent Parent QtObject of this list.
    def __init__(self, parent = None):
        super().__init__(parent)

        self.addRoleName(self.IdRole, "id")
        self.addRoleName(self.NameRole, "name")
        self.addRoleName(self.ColourRole, "colour")
        self.addRoleName(self.IndexRole, "index")

        self._add_global = False

        self._active_extruder_stack = None

        #Listen to changes.
        manager = ExtruderManager.getInstance()
        manager.extrudersChanged.connect(self._updateExtruders) #When the list of extruders changes in general.

        self._updateExtruders()

        manager.activeExtruderChanged.connect(self._onActiveExtruderChanged)
        self._onActiveExtruderChanged()

    def setAddGlobal(self, add):
        if add != self._add_global:
            self._add_global = add
            self._updateExtruders()
            self.addGlobalChanged.emit()

    addGlobalChanged = pyqtSignal()

    @pyqtProperty(bool, fset = setAddGlobal, notify = addGlobalChanged)
    def addGlobal(self):
        return self._add_global

    def _onActiveExtruderChanged(self):
        manager = ExtruderManager.getInstance()
        active_extruder_stack = manager.getActiveExtruderStack()
        if self._active_extruder_stack != active_extruder_stack:
            if self._active_extruder_stack:
                self._active_extruder_stack.containersChanged.disconnect(self._onExtruderStackContainersChanged)

            if active_extruder_stack:
                # Update the model when the material container is changed
                active_extruder_stack.containersChanged.connect(self._onExtruderStackContainersChanged)
            self._active_extruder_stack = active_extruder_stack


    def _onExtruderStackContainersChanged(self, container):
        # The ExtrudersModel needs to be updated when the material-name or -color changes, because the user identifies extruders by material-name
        if container.getMetaDataEntry("type") == "material":
            self._updateExtruders()

    modelChanged = pyqtSignal()

    ##  Update the list of extruders.
    #
    #   This should be called whenever the list of extruders changes.
    def _updateExtruders(self):
        changed = False

        if self.rowCount() != 0:
            self.clear()
            changed = True

        global_container_stack = UM.Application.getInstance().getGlobalContainerStack()
        if global_container_stack:
            if self._add_global:
                material = global_container_stack.findContainer({ "type": "material" })
                colour = material.getMetaDataEntry("color_code", default = self.defaultColours[0]) if material else self.defaultColours[0]
                item = {
                    "id": global_container_stack.getId(),
                    "name": "Global",
                    "colour": colour,
                    "index": -1
                }
                self.appendItem(item)
                changed = True

            machine_extruders = [extruder for extruder in ExtruderManager.getInstance().getMachineExtruders(global_container_stack.getId())]
            for extruder in machine_extruders:
                extruder_name = extruder.getName()
                material = extruder.findContainer({ "type": "material" })
                if material:
                    extruder_name = "%s (%s)" % (material.getName(), extruder_name)
                position = extruder.getMetaDataEntry("position", default = "0")  # Get the position
                try:
                    position = int(position)
                except ValueError: #Not a proper int.
                    position = -1
                default_colour = self.defaultColours[position] if position >= 0 and position < len(self.defaultColours) else self.defaultColours[0]
                colour = material.getMetaDataEntry("color_code", default = default_colour) if material else default_colour
                shade = self.shadeAmount * position / (len(machine_extruders) - 1) if len(machine_extruders) > 1 else 0
                item = { #Construct an item with only the relevant information.
                    "id": extruder.getId(),
                    "name": extruder_name,
                    "colour": self._colourShade(colour, shade),
                    "index": position
                }
                self.appendItem(item)
                changed = True

        if changed:
            self.sort(lambda item: item["index"])
            self.modelChanged.emit()

    ##  Create a shade of a base colour that is either brighter or darker, depending on the
    #   brightness of the base colour.
    #
    #   \param base_colour \type{UM.Math.Color} Base colour to derive a shade of
    #   \param shade \type{float} Amount by which to shade the colour (0: don't shade, 1: full black/white)
    def _colourShade(self, base_colour, shade):
        colour_shade = base_colour
        if shade > 0:
            new_colour = UM.Math.Color.Color.fromRGBString(base_colour)
            if (new_colour.r + new_colour.g + new_colour.b) / 3 < .5:
                mix = 1 # lighten the shade
            else:
                mix = 0 # darken the shade
            new_colour.setValues(
                new_colour.r * (1 - shade) + shade * mix,
                new_colour.g * (1 - shade) + shade * mix,
                new_colour.b * (1 - shade) + shade * mix,
                1.0
            )
            colour_shade = new_colour.toRGBString()

        return colour_shade
