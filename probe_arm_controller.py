# Blocking Klipper controller for the external nRF probe-arm firmware.
#
# The nRF command inputs are active-low and its SUCCESS / ERROR outputs are
# active-high.  This module owns all five GPIOs so status edges can complete a
# blocked G-Code command without needing to acquire Klipper's G-Code mutex.

import logging


COMMAND_PATTERNS = {
    "HOME": (True, False, False),
    "ARM_OUT": (False, True, False),
    "ARM_IN": (False, False, True),
    "TUNE_ARM_OUT_MORE_NEGATIVE": (True, True, False),
    "TUNE_ARM_OUT_LESS_NEGATIVE": (True, False, True),
}


class ProbeArmController:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")

        self.pulse_time = config.getfloat(
            "pulse_time", 0.250, above=0.0
        )
        self.timeout = config.getfloat("timeout", 10.0, above=0.0)
        self.status_clear_timeout = config.getfloat(
            "status_clear_timeout", 2.0, above=0.0
        )
        self.settle_time = config.getfloat(
            "settle_time", 0.500, minval=0.0
        )

        ppins = self.printer.lookup_object("pins")
        self.command_pins = []
        for option in ("home_pin", "arm_out_pin", "arm_in_pin"):
            pin = ppins.setup_pin("digital_out", config.get(option))
            pin.setup_max_duration(0.0)
            # Active-low command: HIGH is safe at startup and shutdown.
            pin.setup_start_value(1.0, 1.0)
            self.command_pins.append(pin)

        self.mcu = self.command_pins[0].get_mcu()
        if any(pin.get_mcu() is not self.mcu for pin in self.command_pins[1:]):
            raise config.error("Probe arm command pins must be on one MCU")
        self.next_print_time = 0.0

        self.success_state = False
        self.error_state = False
        self.busy = False
        self.operation = "IDLE"
        self.result = "IDLE"
        self.completion = None
        self.status_clear_completion = None

        buttons = self.printer.load_object(config, "buttons")
        buttons.register_buttons(
            [config.get("success_pin"), config.get("error_pin")],
            self._status_callback,
        )

        self.gcode.register_command(
            "PROBE_ARM_HOME", self.cmd_HOME,
            desc="Home the external probe arm and wait for its result",
        )
        self.gcode.register_command(
            "PROBE_ARM_OUT", self.cmd_ARM_OUT,
            desc="Move the external probe arm out and wait for its result",
        )
        self.gcode.register_command(
            "PROBE_ARM_IN", self.cmd_ARM_IN,
            desc="Move the external probe arm in and wait for its result",
        )
        self.gcode.register_command(
            "PROBE_ARM_OUT_MORE_NEGATIVE",
            self.cmd_TUNE_ARM_OUT_MORE_NEGATIVE,
            desc="Tune the probe arm-out position more negative",
        )
        self.gcode.register_command(
            "PROBE_ARM_OUT_LESS_NEGATIVE",
            self.cmd_TUNE_ARM_OUT_LESS_NEGATIVE,
            desc="Tune the probe arm-out position less negative",
        )
        self.gcode.register_command(
            "QUERY_PROBE_ARM", self.cmd_QUERY,
            desc="Report external probe-arm controller state",
        )

    def _status_callback(self, eventtime, state):
        self.success_state = bool(state & 0x01)
        self.error_state = bool(state & 0x02)
        logging.info(
            "Probe arm status at %.6f: SUCCESS=%s ERROR=%s",
            eventtime, self.success_state, self.error_state,
        )
        if not self.busy:
            return
        # ERROR wins if the firmware ever presents both signals together.
        if (self.error_state and self.completion is not None
                and not self.completion.test()):
            self.completion.complete("ERROR")
        elif (self.success_state and self.completion is not None
              and not self.completion.test()):
            self.completion.complete("SUCCESS")
        elif (not self.success_state and not self.error_state
              and self.status_clear_completion is not None
              and not self.status_clear_completion.test()):
            self.status_clear_completion.complete("IDLE")

    def _schedule_command(self, pattern, pulse_time):
        now = self.reactor.monotonic()
        min_schedule = self.mcu.min_schedule_time()
        print_time = self.mcu.estimated_print_time(now + min_schedule)
        start_time = max(print_time, self.next_print_time)
        end_time = start_time + pulse_time

        # Queue every command pin at the same MCU print times.  This makes the
        # intended three-pin pattern stable without host-side timing skew.
        for pin, active in zip(self.command_pins, pattern):
            pin.set_digital(start_time, 0 if active else 1)
        for pin in self.command_pins:
            pin.set_digital(end_time, 1)

        self.next_print_time = end_time + min_schedule
        return start_time, end_time

    def _run_command(self, gcmd, operation):
        if self.busy:
            raise gcmd.error(
                "Probe arm is already busy with %s" % (self.operation,)
            )
        if self.success_state or self.error_state:
            active = []
            if self.success_state:
                active.append("SUCCESS")
            if self.error_state:
                active.append("ERROR")
            raise gcmd.error(
                "Probe arm status is not idle (%s is high)" % (
                    " + ".join(active),
                )
            )

        pulse_time = gcmd.get_float(
            "PULSE", self.pulse_time, above=0.0
        )
        timeout = gcmd.get_float("TIMEOUT", self.timeout, above=0.0)

        # Arm movement must not overtake toolhead moves queued before this
        # command (for example, the Euclid safe staging move).
        toolhead = self.printer.lookup_object("toolhead")
        wait_started = self.reactor.monotonic()
        print_time, estimated_time, lookahead_empty = toolhead.check_busy(
            wait_started
        )
        logging.info(
            "Probe arm %s: wait_moves begin at %.6f "
            "(print_time=%.6f estimated=%.6f lookahead_empty=%s)",
            operation, wait_started, print_time, estimated_time,
            lookahead_empty,
        )
        toolhead.wait_moves()
        wait_finished = self.reactor.monotonic()
        print_time, estimated_time, lookahead_empty = toolhead.check_busy(
            wait_finished
        )
        logging.info(
            "Probe arm %s: wait_moves end at %.6f after %.3fs "
            "(print_time=%.6f estimated=%.6f lookahead_empty=%s)",
            operation, wait_finished, wait_finished - wait_started,
            print_time, estimated_time, lookahead_empty,
        )

        self.busy = True
        self.operation = operation
        self.result = "RUNNING"
        self.completion = self.reactor.completion()
        self.status_clear_completion = self.reactor.completion()
        command_started = self.reactor.monotonic()
        logging.info(
            "Probe arm %s: command started at %.6f", operation,
            command_started,
        )

        try:
            pulse_start, pulse_end = self._schedule_command(
                COMMAND_PATTERNS[operation], pulse_time
            )
            logging.info(
                "Probe arm %s: MCU pulse scheduled %.6f..%.6f",
                operation, pulse_start, pulse_end,
            )
            deadline = self.reactor.monotonic() + pulse_time + timeout
            result = self.completion.wait(deadline, "TIMEOUT")
            self.result = result

            if result in ("SUCCESS", "ERROR"):
                result_time = self.reactor.monotonic()
                logging.info(
                    "Probe arm %s: %s latched at %.6f after %.3fs; "
                    "waiting for status LOW",
                    operation, result, result_time,
                    result_time - command_started,
                )
                clear_deadline = result_time + self.status_clear_timeout
                clear_result = self.status_clear_completion.wait(
                    clear_deadline, "STATUS_STUCK"
                )
                if clear_result != "IDLE":
                    self.result = "STATUS_STUCK"
                elif self.settle_time > 0.0:
                    settle_started = self.reactor.monotonic()
                    logging.info(
                        "Probe arm %s: status LOW at %.6f; settling %.3fs",
                        operation, settle_started, self.settle_time,
                    )
                    self.reactor.pause(settle_started + self.settle_time)
        finally:
            self.busy = False
            self.operation = "IDLE"
            self.completion = None
            self.status_clear_completion = None

        if self.result == "SUCCESS":
            logging.info(
                "Probe arm %s: returning to G-Code at %.6f",
                operation, self.reactor.monotonic(),
            )
            gcmd.respond_info("Probe arm %s: SUCCESS" % (operation,))
            return
        if self.result == "ERROR":
            raise gcmd.error("Probe arm %s: ERROR" % (operation,))
        if self.result == "STATUS_STUCK":
            raise gcmd.error(
                "Probe arm %s: status did not return LOW within %.3f seconds"
                % (operation, self.status_clear_timeout)
            )
        raise gcmd.error(
            "Probe arm %s: TIMEOUT after %.3f seconds" % (
                operation, timeout,
            )
        )

    def cmd_HOME(self, gcmd):
        self._run_command(gcmd, "HOME")

    def cmd_ARM_OUT(self, gcmd):
        self._run_command(gcmd, "ARM_OUT")

    def cmd_ARM_IN(self, gcmd):
        self._run_command(gcmd, "ARM_IN")

    def cmd_TUNE_ARM_OUT_MORE_NEGATIVE(self, gcmd):
        self._run_command(gcmd, "TUNE_ARM_OUT_MORE_NEGATIVE")

    def cmd_TUNE_ARM_OUT_LESS_NEGATIVE(self, gcmd):
        self._run_command(gcmd, "TUNE_ARM_OUT_LESS_NEGATIVE")

    def cmd_QUERY(self, gcmd):
        gcmd.respond_info(
            "Probe arm: busy=%s operation=%s result=%s SUCCESS=%s ERROR=%s"
            % (
                self.busy,
                self.operation,
                self.result,
                "HIGH" if self.success_state else "LOW",
                "HIGH" if self.error_state else "LOW",
            )
        )

    def get_status(self, eventtime):
        return {
            "busy": self.busy,
            "operation": self.operation,
            "result": self.result,
            "success": self.success_state,
            "error": self.error_state,
        }


def load_config(config):
    return ProbeArmController(config)
