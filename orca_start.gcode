; ESTIMATOR_ADD_TIME 480 Heating Up and Priming
SET_PRINT_STATS_INFO TOTAL_LAYER={total_layer_count}
G92 E0          ; Set extruder position to 0
M106 S0       ; Turn-off part cooling fan
M220 S100   ; Reset Feedrate
M221 S100   ; Reset Flowrate

SET_HEATER_TEMPERATURE HEATER=extruder TARGET=140
SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET={bed_temperature_initial_layer_single}
TEMPERATURE_WAIT SENSOR=heater_bed MINIMUM={bed_temperature_initial_layer_single-6}
TEMPERATURE_WAIT SENSOR=extruder MINIMUM=140

; First Home the X-Y axes
G28 X Y

STABLE_Z_HOME  ; instead of G28 Z

EUCLID_PROBE_BEGIN_BATCH

CALIBRATE_Z BED_POSITION={(adaptive_bed_mesh_min[0]+adaptive_bed_mesh_max[0])/2},{(adaptive_bed_mesh_min[1]+adaptive_bed_mesh_max[1])/2}

; Further increase extruder temperature while we are doing bed mesh.
{if filament_type[0] == "ABS" or filament_type[0] == "PLA" }
SET_HEATER_TEMPERATURE HEATER=extruder TARGET={nozzle_temperature_initial_layer[0] - 70}
{endif}
; ============================== Bed Mesh Stuff ====================================
;BED_MESH_CLEAR
; Always pass `ADAPTIVE_MARGIN=0` because Orca has already handled `adaptive_bed_mesh_margin` internally
BED_MESH_CALIBRATE mesh_min={adaptive_bed_mesh_min[0]},{adaptive_bed_mesh_min[1]} mesh_max={adaptive_bed_mesh_max[0]},{adaptive_bed_mesh_max[1]} ADAPTIVE_MARGIN=0 ALGORITHM=[bed_mesh_algo] ADAPTIVE=1 PROFILE="live-adaptive"
BED_MESH_PROFILE   SAVE="live-adaptive"
BED_MESH_PROFILE   LOAD="live-adaptive"
; ===================================================================================

EUCLID_PROBE_END_BATCH
ASSERT_PROBE_STOWED

{if curr_bed_type=="Textured PEI Plate"}
START_PRINT HOTEND_TEMP=[nozzle_temperature_initial_layer] BED_TEMP={bed_temperature_initial_layer_single} Z_ADJUST=0.025 TIMELAPSE=1
{else}
START_PRINT HOTEND_TEMP=[nozzle_temperature_initial_layer] BED_TEMP={bed_temperature_initial_layer_single} Z_ADJUST=0 TIMELAPSE=1
{endif}

