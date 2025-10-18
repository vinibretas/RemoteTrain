# ------------- main.py ------------- #
import network, socket, ure, json, uerrno
from machine import Pin, PWM
from time import sleep_ms, time, sleep_us

DEBUG = True
DRY_RUN = 0

_ERRNO_EAGAIN = uerrno.EAGAIN
try:
    _ERRNO_EWOULDBLOCK = uerrno.EWOULDBLOCK
except AttributeError:              # not available ⇒ treat as EAGAIN
    _ERRNO_EWOULDBLOCK = _ERRNO_EAGAIN

COMMAND_MAX_COUNT = 8

def _log(*a):
    if DEBUG:
        print("[LOG]", *a)

class IMarker:
    def __init__(self, start_at = 0):
        self.imark_counter = start_at - 1

    def imark(self, reset = False):
        if reset: self.imark_counter = start_at
        # Increase counter before returning it
        self.imark_counter += 1
        # retrieves current I counter
        return self.imark_counter
    def imark_range(self, max_ = None,min_ = None, step = 1):
        if max_ is None:
            assert False, "Must provide `max_` arg"
        else:
            if min_ is not None:
                min_,max_ = max_,min_
        if min_ is None:
            min_ = 0
        output = []
        for k in range(min_,max_,step):
            output.append(self.imark())
        return tuple(output)

    def __str__(self):
        return f"{self.imark_counter}"

# Enum for commands
CMD = IMarker(1)

STOP = CMD.imark()
FOWARD = CMD.imark()
BACKWARD = CMD.imark()
SPEEDUP = CMD.imark()
SPEEDOWN = CMD.imark()

OFFSET = COMMAND_MAX_COUNT - CMD.imark_counter
OFFSET = 0
_log(f"OFFSET = {OFFSET}")

assert CMD.imark_counter <= COMMAND_MAX_COUNT, f"Commands surpassed maximum limit of {COMMAND_MAX_COUNT}, got {CMD.imark_counter}"

# Modes enum
MD = IMarker()
RX_MODE = MD.imark()
BRIDGE_MODE = MD.imark()

DEFAULT_MODE = RX_MODE

# Edges enum
EDGE = IMarker()
RISING = EDGE.imark()
FALLING = EDGE.imark()
# ------------------------------------------------------------------------
#  Hardware Abstractions
# ------------------------------------------------------------------------
class Train:
    """Generic H-bridge DC motor train with direction pins"""
    def __init__(self, name, freq=1000, rx_pin = None, foward_pin = None, backward_pin = None, pwm_pin = None):
        self.pins_dict = {"rx_pin":rx_pin,"foward_pin":foward_pin,"backward_pin":backward_pin,"pwm_pin":pwm_pin}
        self.pins_str = ", ".join(f"{k} = {v}" for k,v in self.pins_dict.items())
        if all(v is None for v in self.pins_dict.values()):
            raise RuntimeError("Must providde either rx_pin or BRIDGE_MODE pins")
        if rx_pin is not None:
            if any(k is not None for k in [foward_pin, backward_pin, pwm_pin]):
                raise RuntimeError(f"Direct drive move is incompatible with rx mode. Provide either rx_pin or foward, backward and pwm pins\nGot: {self.pins_str}")
            self.mode = RX_MODE
        elif all(k is not None for k in [foward_pin, backward_pin, pwm_pin]):
            self.mode = BRIDGE_MODE
        else:
            raise RuntimeError(f"Missing bridge mode parameters. Got: foward_pin={foward_pin}, backward_pin={backward_pin}, pwm_pin={pwm_pin}")


        if DEBUG:
            print(f"Current Mode: {self.mode}")
        self.name = name
        self.freq = freq
        self.period = 1 / freq
        self.rx = Pin(rx_pin, Pin.OUT, value=0) if self.mode is RX_MODE else None
        self.fwd = Pin(foward_pin, Pin.OUT,value=0) if self.mode is BRIDGE_MODE else None
        self.bwd = Pin(backward_pin, Pin.OUT,value=0) if self.mode is BRIDGE_MODE else None
        self.pwm = PWM(Pin(pwm_pin)) if self.mode is BRIDGE_MODE else None
        if self.pwm:
            self.pwm.freq(self.freq)

        if DEBUG:
            print(f"self.rx = {self.rx}")
            print(f"self.fwd = {self.fwd}")
            print(f"self.bwd = {self.bwd}")
            print(f"self.pwm = {self.pwm}")
        self._speed = 0
        self.stop()

    # ---------- public API ----------

    def send_command(self, command, edge = RISING):
        command += OFFSET
        if not self.rx: 
            raise RuntimeError(".send_command method only compatible with rx mode")
        print(f"\n\nMocked send command: Would send {command} pulses!\n\n")
        period_us = int(500_000 / self.freq)   # half-period in µs
        edge = 1 if edge is RISING else 0
        for k in range(command):
            self.rx.value(edge)
            sleep_us(period_us)
            self.rx.value(not edge)
            sleep_us(period_us)
        self.rx.value(0)

    def mocked(self, name):
        print(f"\n\nMocked funcionality: {name}\n\n")

    def forward(self, speed_percent=None):
        if speed_percent is not None:
            self.set_speed(speed_percent)
        elif self._speed == 0:
            self._speed = 50
        if self.mode is BRIDGE_MODE:
            self.fwd.value(1);
            self.bwd.value(0)
        else:
            self.send_command(FOWARD)
        self.mocked("foward")
        return

    def backward(self, speed_percent=None):
        if speed_percent is not None:
            self.set_speed(speed_percent)
        if self.mode is BRIDGE_MODE:
            self.fwd.value(0);
            self.bwd.value(1)
        else:
            self.send_command(BACKWARD)
        self.mocked("backward")
        return

    def is_moving(self):
        return self._speed > 0

    def change_speed(self, delta):
        """±delta percentage points, clamped 0-100."""
        if self.mode is BRIDGE_MODE:
            self.set_speed(self._speed + delta)
        else:
            self._speed += delta
            if delta > 0:
                self.send_command(SPEEDUP)
            elif delta < 0:
                self.send_command(SPEEDOWN)
        self.mocked(f"change_speed from {self._speed - delta} to {self._speed} ({'+' if delta > 0 else '-'}{delta if delta > 0 else -delta})")
        return

    def toggle(self):
        if self.is_moving():
            self.stop()
            mocked_message = "from moving to stopped"
        else:                       # restart in last dir at 50 %
            self.forward(50 if self.mode is BRIDGE_MODE else None)
            mocked_message = "from stopped to moving"
        self.mocked(f"toggled {mocked_message}")
        return

    def stop(self):
        if self.mode is BRIDGE_MODE:
            self.fwd.value(0);
            self.bwd.value(0)
            self.pwm.duty_u16(0)
        else:
            self.send_command(STOP)
        self._speed = 0
        self.mocked("stop")
        return

    def set_speed(self, speed_percent: int):
        """0–100 → 0–65535 duty"""

        self._speed = max(0, min(100, speed_percent))
        duty = int(self._speed * 65535 // 100)
        self._pwm.duty_u16(duty)
        self.mocked(f"set_speed to {self._speed}, duty: {duty}")
        return

    # ---------- helpers ----------
    def serialize(self):
        return {"name": self.name, "speed": self._speed, "freq": self.freq}

# ------------------------------------------------------------------------
#  Train Manager – Data structure to store trains instances
# ------------------------------------------------------------------------
class TrainManager:
    def __init__(self):
        self._trains = {}

    def add(self, train: Train):
        self._trains[train.name] = train

    def get(self, name) -> Train:
        return self._trains[name]

    def all(self):
        return list(self._trains.values())

    # REST-style helpers --------------------------------------------------
    def handle_action(self, train_name, action, value=None):
        train = self.get(train_name)
        if action == "forward":
            train.forward(int(value) if value else None)
        elif action == "backward":
            train.backward(int(value) if value else None)
        elif action == "stop":
            train.stop()
        elif action == "speed":
            train.set_speed(int(value))
        elif action == "inc":
            train.change_speed(+10)
        elif action == "dec":
            train.change_speed(-10)
        elif action == "toggle":
            train.toggle()
        return train.serialize()

    def create_from_args(self, name, rx_pin, freq, mode=DEFAULT_MODE):
        if DEBUG:
            print(f"Called `create_from_args(self(TrainManager class), name={name}, rx_pin={rx_pin}, mode={mode})`")
        rx = int(rx_pin)
        f   = int(freq)
        # simple heuristic: dir pins = pwm±1
        train   = Train(name, dir_pin_1=rx-1, dir_pin_2=rx+1, rx_pin=pwm, freq=f)
        self.add(train)
        return train.serialize()

# ------------------------------------------------------------------------
#  Wi-Fi Access Point
# ------------------------------------------------------------------------
def start_ap():
    ap = network.WLAN(network.AP_IF)
    ap.config(essid="PicoMotor", password="12345678")
    ap.active(True)
    while not ap.active():
        sleep_ms(100)
    print("AP started →", ap.ifconfig()[0])

# ------------------------------------------------------------------------
#  Minimal HTTP server – no blocking on multiple clients
# ------------------------------------------------------------------------

class WebServer:
    _html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{font-family:sans-serif;text-align:center;background:#111;color:#eee}
h1{margin-top:.5em}.card{display:inline-block;padding:1em;margin:1em;border:1px solid #555;border-radius:8px}
button,input[type=range],input[type=number],input[type=text]{width:90%%;padding:.6em;margin:.3em;background:#333;color:#fff;border:none;border-radius:6px;font-size:1em}
button:active{background:#555}
form{border:1px solid #333;padding:1em;border-radius:8px;margin:1em;display:inline-block}
</style></head><body>
<h1>Controle Trens</h1>

<form onsubmit="addTrain(event)">
  <h2>Adicionar Train</h2>
  <input type="text"   id="n"  placeholder="Nome" value ="TremB" required>
  <input type="number" id="p"  placeholder="Porta" value="15" required>
  <input type="number" id="f"  placeholder="Freq (Hz)" value="2000" required>
  <button>Adicionar</button>
</form>

<div id="cards"></div>
<script>
function api(p){return fetch(p).then(r=>r.json())}
function addTrain(e){
  e.preventDefault();
  const name=n.value.trim(), pin=p.value.trim(), freq=f.value.trim();
  if(!name||!pin||!freq)return;
  api(`/add?name=${name}&pwm=${pin}&freq=${freq}`).then(refresh);
  e.target.reset();
}
function card(train){return`
<div class="card" id="${train.name}">
  <h2>${train.name} <small>${train.freq} Hz</small></h2>
  <button onclick="api('/${train.name}/forward')">⏩ Para Frente</button>
  <button onclick="api('/${train.name}/backward')">⏪ Ré</button>
  <button onclick="api('/${train.name}/toggle')">
      ${train.speed>0?'⏹ Parar':'▶ Andar'}</button><br>
  <button onclick="api('/${train.name}/inc')">➕ Mais rápido</button>
  <button onclick="api('/${train.name}/dec')">➖ Mais devagar</button>
  <p>Velocidade&nbsp;${train.speed}%</p>
</div>`}
function refresh(){api('/status').then(a=>cards.innerHTML=a.map(card).join(''))}
setInterval(refresh,1500);refresh();
</script></body></html>"""

    def __init__(self, manager):
        self._m = manager
        addrinfo = socket.getaddrinfo("0.0.0.0", 80)
        addr = addrinfo[0][-1]
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.loop_count = 0
        timeout = 50
        t0 = time()
        sucess_bind = False
        while time() - t0 < timeout:
            try:
                self._sock.bind(addr)
                sucess_bind = True
                break
            except OSError as e:
                print(f"Failed ({e}), trying again ({(timeout - time() + t0):.2f}s left)")
                sleep_ms(1000)
        if sucess_bind:
            if DEBUG:
                print(f"Bound socket ({self._sock}) to address: {addr}")
        else:
            print("\n\n\n\nBind failed!!!!!!\n\n\n\n\n")
            raise OSError("Failed to bind socket")
        self._sock.listen(5)
        self._sock.settimeout(0)       # non-blocking listener

    # ------------------------------------------------------------
    def loop(self):
        self.loop_count += 1
        try:
            cl, addr = self._sock.accept()
        except OSError as e:
            if DEBUG and (not self.loop_count % 1000 or self.loop_count == 1):
                print(f"Failed to accept client ({self.loop_count}): error=`{e}`")
            #if e.args[0] in (uerrno.EAGAIN, uerrno.EWOULDBLOCK):
            if e.args[0] in (uerrno.EAGAIN, 1):
                return                  # no pending client
            raise

        _log("Client", addr)
        cl.settimeout(2)               # block up to 2 s for HTTP request

        try:
            req = cl.recv(1024)
        except OSError as e:
            _log("recv() error:", e)
            cl.close(); return

        if not req:
            _log("empty request"); cl.close(); return

        try:
            route = ure.search(r"GET /(.*?) ", req.decode()).group(1)
        except Exception as e:
            _log("parse error:", e)
            self._send(cl, 400, "text/plain", "Bad request")
            cl.close(); return

        if DEBUG and route:
            print(f"Route = `{route}`")

        # ---------- Static page ----------
        if route in ("", "index.html"):
            self._send(cl, 200, "text/html", self._html)

        # ---------- API ----------
        elif route == "status":
            data = [train.serialize() for train in self._m.all()]
            self._send(cl, 200, "application/json", json.dumps(data))

        # ---------- Add train ----------
        elif route.startswith("add?"):
            qs = dict(s.split("=",1) for s in route[4:].split("&"))
            try:
                state = self._m.create_from_args(qs["name"], qs["pwm"], qs["freq"])
                self._send(cl, 200, "application/json", json.dumps(state))
            except Exception as e:
                _log("add error:", e)
                self._send(cl, 400, "text/plain", "Bad add params")

        else:
            parts = route.split("?")
            core = parts[0].split("/")
            if len(core) == 2:
                name, action = core
                val = None
                if len(parts) > 1 and parts[1].startswith("val="):
                    val = parts[1][4:]
                try:
                    state = self._m.handle_action(name, action, val)
                    self._send(cl, 200, "application/json", json.dumps(state))
                except KeyError:
                    _log("unknown train", name)
                    self._send(cl, 404, "text/plain", "Train not found")
                except Exception as e:
                    _log("handler error:", e)
                    self._send(cl, 500, "text/plain", "Internal error")
            else:
                self._send(cl, 400, "text/plain", "Bad request")

        cl.close()

    # --------------- helpers ----------------
    def _send(self, cl, status, ctype, payload):
        try:
            cl.send("HTTP/1.1 %d OK\r\nContent-Type:%s\r\nContent-Length:%d\r\n\r\n"
                    % (status, ctype, len(payload)))
            cl.send(payload)
            if DEBUG:
                print(f"Sent payload!")
        except Exception as e:
            if DEBUG:
                print(f"Failed to send payload: error=`{e}`")
            _log("send error:", e)



# ------------------------------------------------------------------------
#  Main bootstrap
# ------------------------------------------------------------------------
def main():
    if DEBUG or DRY_RUN:
        print(f"Warning: Remember to turn off DEBUG (currently {bool(DEBUG)}) and or DRY_RUN (currently {bool(DRY_RUN)}) off")
    t1 = Train("TestTrain", rx_pin = 4, freq=500)
    #  t2 = Train("TestTrain", backward_pin = 4, foward_pin=5,pwm_pin=6)
    #  t3 = Train("TestTrain", backward_pin = 1, foward_pin=1, rx_pin=1)
    #  t4 = Train("TestTrain")
    #  t5 = Train("TestTrain", backward_pin = 1)
    assert not DRY_RUN, "DRY_RUN mode on, exiting..."
    # ---- create your trains here ----
    mgr = TrainManager()
    # TODO: adjust pins
    mgr.add(t1)
    #  mgr.add(Train("TremA", dir_pin_1=2, dir_pin_2=3, rx_pin=4, freq=1500))
    #  mgr.add(Train("M2", dir_pin_1=5, dir_pin_2=6, rx_pin=7))
    start_ap()
    server = WebServer(mgr)
    print("Server running …")

    while True:
        server.loop()          # non-blocking, returns immediately
        sleep_ms(25)           # cooperative multitasking window

if __name__ == "__main__":
    main()





