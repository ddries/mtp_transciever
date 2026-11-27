"""Mode selection and per-mode settings, without hardware (pyrf24 and the radio are stubbed)."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

driver = types.ModuleType("pyrf24")
driver.RF24 = object
for name in ("RF24_PA_MIN", "RF24_PA_LOW", "RF24_PA_HIGH", "RF24_PA_MAX",
             "RF24_250KBPS", "RF24_1MBPS", "RF24_2MBPS"):
    setattr(driver, name, name)
sys.modules.setdefault("pyrf24", driver)

import main  # noqa: E402
from mtp import p2p  # noqa: E402
from mtp.modes import nm, qm, sri, mrm  # noqa: E402


class Launcher(unittest.TestCase):
    def config(self, **values) -> Path:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = directory / "config.json"
        path.write_text(json.dumps(values))
        return path

    def launch(self, *argv, stick_ok=True, run_result=True):
        self.stick_calls = []

        def stick(action):
            self.stick_calls.append(action)
            return stick_ok

        with patch("main.run", side_effect=self.fake_run(run_result)) as run, \
                patch("main.stick", side_effect=stick), patch.object(main.Path, "mkdir"):
            ok = main.main(list(argv))
        return ok, (run.call_args.args if run.called else None)

    def fake_run(self, result):
        def run(mode, config):
            self.stick_calls.append("run")
            if isinstance(result, BaseException):
                raise result
            return result
        return run

    def test_stick_mounted_before_and_unmounted_after(self):
        box = str(self.config())
        self.launch("--mode", "qm", "--role", "tx", "--config", box)
        self.assertEqual(self.stick_calls, ["mount", "run", "umount"])
        # also after a failed transfer, and after Ctrl+C
        self.launch("--mode", "qm", "--role", "rx", "--config", box, run_result=False)
        self.assertEqual(self.stick_calls, ["mount", "run", "umount"])
        with self.assertRaises(KeyboardInterrupt):
            self.launch("--mode", "nm", "--role", "rx", "--config", box, run_result=KeyboardInterrupt())
        self.assertEqual(self.stick_calls, ["mount", "run", "umount"])

    def test_no_stick_stops_before_the_radio(self):
        ok, call = self.launch("--mode", "sri", "--role", "rx", "--config", str(self.config()),
                               stick_ok=False)
        self.assertFalse(ok)
        self.assertIsNone(call)
        self.assertEqual(self.stick_calls, ["mount"])

    def test_keep_mounted_no_mount_and_other_folders(self):
        box = str(self.config())
        self.launch("--mode", "qm", "--role", "tx", "--config", box, "--keep-mounted")
        self.assertEqual(self.stick_calls, ["mount", "run"])
        self.launch("--mode", "qm", "--role", "tx", "--config", box, "--no-mount")
        self.assertEqual(self.stick_calls, ["run"])
        self.launch("--mode", "nm", "--role", "tx", "--config", box, "--usb", "/mnt/usb/nm")
        self.assertEqual(self.stick_calls, ["mount", "run", "umount"])
        self.launch("--mode", "qm", "--role", "tx", "--config", box, "--usb", "/tmp/stick")
        self.assertEqual(self.stick_calls, ["run"])                  # not the stick: left alone

    def test_mode_files_are_valid_and_complete(self):
        for mode in ("qm", "sri", "mrm", "nm"):
            with self.subTest(mode=mode):
                config = json.loads((main.CONFIGS / f"{mode}.json").read_text())
                self.assertEqual(config["mode"], mode)
                self.assertEqual(config["usb_device"], "/mnt/usb")
                self.assertEqual(config["pa_level"], "min")      # 10 mW e.i.r.p. on a fixed channel
                self.assertNotIn("tx_rx_mode", config)           # the role belongs to the box
        for mode in ("qm", "sri", "mrm"):
            config = json.loads((main.CONFIGS / f"{mode}.json").read_text())
            self.assertEqual((config["channel"], config["data_rate"], config["address"]),
                             (74, "250k", "TeamC"))

    def test_mode_file_plus_role(self):
        ok, (mode, config) = self.launch("--mode", "sri", "--role", "rx",
                                         "--config", str(self.config()))
        self.assertTrue(ok)
        self.assertEqual(mode, "sri")
        self.assertEqual((config["tx_rx_mode"], config["channel"], config["address"]), ("rx", 74, "TeamC"))

    def test_box_config_overrides_mode_file_and_cli_overrides_box(self):
        box = self.config(mode="nm", tx_rx_mode="tx", channel=76)
        ok, (mode, config) = self.launch("--config", str(box))
        self.assertEqual((mode, config["tx_rx_mode"]), ("nm", "tx"))
        ok, (mode, config) = self.launch("--config", str(box), "--mode", "qm", "--role", "rx",
                                         "--usb", "/tmp/stick")
        self.assertEqual((mode, config["tx_rx_mode"], config["channel"], config["usb_device"]),
                         ("qm", "rx", 76, "/tmp/stick"))

    def test_out_names_the_received_file(self):
        ok, (mode, config) = self.launch("--mode", "sri", "--role", "rx", "--out", "test_sri.txt",
                                         "--config", str(self.config()))
        self.assertEqual(config["output_name"], "test_sri.txt")

    def test_default_mode_is_qm(self):
        ok, (mode, _) = self.launch("--role", "tx", "--config", str(self.config()))
        self.assertEqual(mode, "qm")

    def test_missing_role_unknown_mode_or_bad_files_fail(self):
        empty = str(self.config())
        for argv in (["--config", empty],                                 # no role anywhere
                     ["--role", "tx", "--config", str(self.config(mode="xx"))],
                     ["--role", "tx", "--config", "/nonexistent/config.json"],
                     ["--role", "tx", "--config", empty, "--configs", "/nonexistent"]):
            with self.subTest(argv=argv):
                ok, call = self.launch(*argv)
                self.assertFalse(ok)
                self.assertIsNone(call)


class PointToPointModes(unittest.TestCase):
    def run_mode(self, module, **config):
        stick = Path(self.enterContext(tempfile.TemporaryDirectory()))
        config = {"usb_device": str(stick), "tx_rx_mode": "rx", "address": "1Node", **config}
        radio = Mock()
        with patch.object(p2p, "setup_radio", return_value=radio) as setup, \
                patch.object(p2p, "receive_file", return_value=True):
            self.assertTrue(module.run(config))
        return setup.call_args.args

    def test_profiles(self):
        # address, channel, pa_level, data_rate, spi_hz
        for module in (qm, sri, mrm):
            with self.subTest(mode=module.__name__):
                self.assertEqual(self.run_mode(module), ("1Node", 74, "min", "250k", 4_000_000))

    def test_receiver_writes_the_named_file(self):
        stick = Path(self.enterContext(tempfile.TemporaryDirectory()))
        config = {"usb_device": str(stick), "tx_rx_mode": "rx", "address": "1Node"}
        for name, expected in ((None, "output.txt"), ("test_sri.txt", "test_sri.txt")):
            with self.subTest(name=name), patch.object(p2p, "setup_radio", return_value=Mock()), \
                    patch.object(p2p, "receive_file", return_value=True) as receive:
                self.assertTrue(sri.run({**config, **({"output_name": name} if name else {})}))
                self.assertEqual(receive.call_args.args[1], stick / expected)
        for bad in ("../x.txt", "a/b.txt", ".hidden", ".."):
            with self.subTest(bad=bad), patch.object(p2p, "setup_radio") as setup:
                self.assertFalse(sri.run({**config, "output_name": bad}))
                setup.assert_not_called()

    def test_config_overrides_profile(self):
        args = self.run_mode(qm, channel=76, data_rate="1m", spi_hz=8_000_000)
        self.assertEqual(args, ("1Node", 76, "min", "1m", 8_000_000))

    def test_bad_values_rejected_before_the_radio(self):
        for bad in ({"channel": 84}, {"pa_level": "huge"}, {"compression": "false"},
                    {"tx_rx_mode": "both"}, {"address": "abc"}):
            with self.subTest(bad=bad), patch.object(p2p, "setup_radio") as setup:
                stick = self.enterContext(tempfile.TemporaryDirectory())
                config = {"usb_device": stick, "tx_rx_mode": "rx", "address": "1Node", **bad}
                self.assertFalse(qm.run(config))
                setup.assert_not_called()


class NetworkMode(unittest.TestCase):
    def stick(self, **files) -> Path:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name, data in files.items():
            (root / name).write_bytes(data)
        return root

    def test_relay_node_arguments(self):
        stick = self.stick()
        argv = nm.arguments({"usb_device": str(stick), "tx_rx_mode": "rx"})
        self.assertEqual(argv, ["--radio", "nrf24", "--ce", "22", "--csn", "0", "--pa", "min",
                                "--spi-hz", "4000000", "--output", str(stick / "output.txt"), "--go"])

    def test_nm_output_name(self):
        stick = self.stick()
        argv = nm.arguments({"usb_device": str(stick), "tx_rx_mode": "rx", "output_name": "test_nm.txt"})
        self.assertEqual(argv[argv.index("--output") + 1], str(stick / "test_nm.txt"))
        self.assertIsNone(nm.arguments({"usb_device": str(stick), "output_name": "../x.txt"}))

    def test_source_node_sends_the_stick_file(self):
        stick = self.stick(**{"desktop.ini": b"x", "nm.txt": b"hello"})
        argv = nm.arguments({"usb_device": str(stick), "tx_rx_mode": "tx"})
        self.assertEqual(argv[-2:], ["--input", str(stick / "nm.txt")])

    def test_source_without_file_or_bad_stick_fails(self):
        self.assertIsNone(nm.arguments({"usb_device": str(self.stick()), "tx_rx_mode": "tx"}))
        self.assertIsNone(nm.arguments({"usb_device": "/nonexistent", "tx_rx_mode": "rx"}))
        self.assertIsNone(nm.arguments({"usb_device": str(self.stick()), "pa_level": "huge"}))

    def test_run_calls_the_nmp_program(self):
        stick = self.stick()
        fake_main = SimpleNamespace(main=Mock(return_value=0))
        with patch.dict(sys.modules, {"mtp.modes.nm.main": fake_main}):
            self.assertTrue(nm.run({"usb_device": str(stick), "tx_rx_mode": "rx"}))
        self.assertIn("--go", fake_main.main.call_args.args[0])

    def test_spi_speed_reaches_pyrf24(self):
        from mtp.modes.nm.radio import NRF24Radio
        device = Mock()
        device.begin.return_value = True
        module = SimpleNamespace(RF24=Mock(return_value=device), RF24_DRIVER="SPIDEV",
                                 RF24_1MBPS=0, RF24_CRC_16=2, RF24_PA_MIN=0, RF24_PA_LOW=1,
                                 RF24_PA_HIGH=2, RF24_PA_MAX=3, RF24_TX_DS=0x20, RF24_TX_DF=0x10)
        with patch("mtp.modes.nm.radio.sys.platform", "linux"), \
                patch.dict("sys.modules", {"pyrf24": module}):
            NRF24Radio(22, 0, "min", 4_000_000)
        module.RF24.assert_called_once_with(22, 0, 4_000_000)


if __name__ == "__main__":
    unittest.main()
