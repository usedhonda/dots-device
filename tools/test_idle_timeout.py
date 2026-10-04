"""Run the firmware's actual idle-return guard with a release crossing a clock tick."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / "firmware/kai_companion/kai_companion.ino").read_text()
guard = next(line.strip() for line in source.splitlines() if "if(page!=HOME" in line and "lastTouchMs" in line)
program = """
#include <cstdint>
#include <cassert>
uint32_t clockMs, now, lastTouchMs;
uint32_t millis(){return clockMs;}
int page=1, HOME=0, targetPage=1, MAX_PAGE=4;
bool fingerDown=false, settling=false, returned=false;
void slideTo(int){returned=true;}
void check(){GUARD}
void scenario(uint32_t loopTime,uint32_t releaseTime,uint32_t checkTime,bool expected){
 now=loopTime;lastTouchMs=releaseTime;clockMs=checkTime;returned=false;
 check();assert(returned==expected);
}
int main(){
 scenario(1000,1001,1001,false);
 scenario(1000,1001,1002,false);
 scenario(0xfffffffe,0xffffffff,0,false);
 scenario(1000,1000,16000,false);
 scenario(1000,1000,16001,true);
 targetPage=3;scenario(1000,1000,61001,false);
 scenario(1000,1000,3601000,false);
 fingerDown=true;scenario(1000,1000,61001,false);
}
""".replace("GUARD", guard)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / "test.cpp").write_text(program)
    subprocess.run(["c++", "-std=c++11", str(path / "test.cpp"), "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)
print("PASS release clock tick, rollover, idle threshold, held finger")
