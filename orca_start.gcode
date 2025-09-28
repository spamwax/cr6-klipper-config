; ESTIMATOR_ADD_TIME 480 Heating Up and Priming
SET_PRINT_STATS_INFO TOTAL_LAYER={total_layer_count}
G92 E0      ; Set extruder position to 0
M106 S0     ; Turn-off part cooling fan
M220 S100   ; Reset Feedrate
M221 S100   ; Reset Flowrate

CLEAR_PAUSE
BED_MESH_CLEAR

{if chamber_temperature[0] > 0 }
; It will only start chamber heater if chamber temp is set in the filament settings.
CHAMBER_HEAT_START TARGET={chamber_temperature[0]} DELTA=1
{endif}

; Adding the following line just to ensure SS knows the idle and starting temperatures
M104 S140

SET_HEATER_TEMPERATURE HEATER=extruder TARGET=140
SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET={bed_temperature_initial_layer_single}
TEMPERATURE_WAIT SENSOR=heater_bed MINIMUM={bed_temperature_initial_layer_single-6}
TEMPERATURE_WAIT SENSOR=extruder MINIMUM=140

; First Home the X-Y axes
G28 X Y
STABLE_Z_HOME  ; instead of G28 Z

SET_GCODE_OFFSET Z=0 MOVE=1

; ____________________________________________________________________________________
EUCLID_PROBE_BEGIN_BATCH

CALIBRATE_Z BED_POSITION={(adaptive_bed_mesh_min[0]+adaptive_bed_mesh_max[0])/2},{(adaptive_bed_mesh_min[1]+adaptive_bed_mesh_max[1])/2}

; Further increase extruder temperature while we are doing bed mesh.
{if filament_type[0] == "ABS" or filament_type[0] == "PLA" }
SET_HEATER_TEMPERATURE HEATER=extruder TARGET={nozzle_temperature_initial_layer[0] - 70}
{endif}

; =============== Bed Mesh Stuff =====================
; Always pass `ADAPTIVE_MARGIN=0` because Orca has already handled `adaptive_bed_mesh_margin` internally
BED_MESH_CALIBRATE mesh_min={adaptive_bed_mesh_min[0]},{adaptive_bed_mesh_min[1]} mesh_max={adaptive_bed_mesh_max[0]},{adaptive_bed_mesh_max[1]} ADAPTIVE_MARGIN=0 ALGORITHM=[bed_mesh_algo] ADAPTIVE=1 PROFILE="live-adaptive"
BED_MESH_PROFILE   SAVE="live-adaptive"
BED_MESH_PROFILE   LOAD="live-adaptive"
; =====================================================

EUCLID_PROBE_END_BATCH
; ____________________________________________________________________________________
ASSERT_PROBE_STOWED

{if nozzle_diameter[0] == 0.4}
{if curr_bed_type=="Textured PEI Plate"}
SET_GCODE_OFFSET Z_ADJUST=-0.0005 MOVE=1
REPORT_Z_OFFSET
{else}
SET_GCODE_OFFSET Z_ADJUST=0.0 MOVE=1
REPORT_Z_OFFSET
{endif}
; ===================================================================================
{elif nozzle_diameter[0] == 0.5}
{if curr_bed_type=="Textured PEI Plate"}
SET_GCODE_OFFSET Z_ADJUST=0.05 MOVE=1
REPORT_Z_OFFSET
{else}
SET_GCODE_OFFSET Z_ADJUST=0.01 MOVE=1
REPORT_Z_OFFSET
{endif}
; ===================================================================================
{elif nozzle_diameter[0] == 0.6}
{if curr_bed_type=="Textured PEI Plate"}
SET_GCODE_OFFSET Z_ADJUST=0.06 MOVE=1
REPORT_Z_OFFSET
{else}
SET_GCODE_OFFSET Z_ADJUST=0.01 MOVE=1
REPORT_Z_OFFSET
{endif}
; ===================================================================================
{endif}

START_PRINT HOTEND_TEMP=[nozzle_temperature_initial_layer] BED_TEMP={bed_temperature_initial_layer_single} CHAMBER_TEMP={chamber_temperature[0]} TIMELAPSE=1

_CLIENT_LINEAR_MOVE Z={first_layer_height + 0.5} F=1000 ABSOLUTE=1 ; Move Z up to avoid nozzle hitting the bed
M400
; GO TO FIRST PRINT POINT
_CLIENT_LINEAR_MOVE X={first_layer_print_min[0]} Y={first_layer_print_min[1]} F=10000 ABSOLUTE=1 ; Move to the first layer print position

; START_PRINT macro will load default bed mesh profile, so we need to load the live-adaptive profile again
BED_MESH_PROFILE LOAD="live-adaptive"

