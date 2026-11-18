import os, subprocess, unittest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://epiccontentcreatorgrants.org/api/public/channels/cruisenewstrivia/destination-agent"
SECRET = "s" * 40

def gate(env):
    script = 'log(){ echo "LOG $*"; }; source ./cnt-destination-gate.sh; cnt_destination_gate; echo "RESULT=$CNT_DESTINATION_SWITCHING"'
    base = {"PATH": os.environ["PATH"]}; base.update(env)
    r = subprocess.run(["bash", "-c", script], cwd=HERE, env=base, capture_output=True, text=True, check=True)
    return r.stdout

class Gate(unittest.TestCase):
    def test_default_off(self):
        out = gate({}); self.assertIn("RESULT=off", out); self.assertNotIn("WARNING", out)
    def test_missing_secret_fails_closed(self):
        out = gate({"CNT_DESTINATION_SWITCHING": "on", "CNT_DESTINATION_AGENT_URL": URL})
        self.assertIn("RESULT=off", out); self.assertIn("SECRET missing", out)
    def test_missing_url_fails_closed(self):
        out = gate({"CNT_DESTINATION_SWITCHING": "on", "CNT_DESTINATION_AGENT_SECRET": SECRET})
        self.assertIn("RESULT=off", out); self.assertNotIn(SECRET, out)
    def test_short_secret_and_bad_url(self):
        self.assertIn("RESULT=off", gate({"CNT_DESTINATION_SWITCHING": "on", "CNT_DESTINATION_AGENT_URL": URL, "CNT_DESTINATION_AGENT_SECRET": "short"}))
        self.assertIn("RESULT=off", gate({"CNT_DESTINATION_SWITCHING": "on", "CNT_DESTINATION_AGENT_URL": "http://evil/x", "CNT_DESTINATION_AGENT_SECRET": SECRET}))
    def test_valid_on(self):
        out = gate({"CNT_DESTINATION_SWITCHING": "on", "CNT_DESTINATION_AGENT_URL": URL, "CNT_DESTINATION_AGENT_SECRET": SECRET})
        self.assertIn("RESULT=on", out); self.assertNotIn(SECRET, out)

class Order(unittest.TestCase):
    def setUp(self): self.s = open(os.path.join(HERE, "run-cnt.sh")).read()
    def test_gate_before_first_encoder_and_agent_after(self):
        main = self.s[self.s.index("\nstart_display\n"):]
        g, f, a = main.index("cnt_destination_gate"), main.index("start_ffmpeg"), main.index("start_agent")
        self.assertTrue(g < f < a)
    def test_agent_only_when_on_and_stopped_first(self):
        fn = self.s[self.s.index("start_agent() {"):]
        self.assertIn('[ "$CNT_DESTINATION_SWITCHING" = on ] || return 0', fn.split("}")[0])
        sd = self.s[self.s.index("shutdown() {"):]
        self.assertLess(sd.index("AGENT_PID"), sd.index("FFMPEG_PID"))
        self.assertLess(sd.index("FFMPEG_PID"), sd.index("stop_chromium"))
    def test_dockerfile_bundles_agent(self):
        d = open(os.path.join(HERE, "Dockerfile.cnt")).read()
        self.assertIn("cnt-destination-agent.py", d); self.assertIn("cnt-destination-gate.sh", d)

if __name__ == "__main__": unittest.main()