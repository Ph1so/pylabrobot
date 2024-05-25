import logging
from typing import List, Optional, Union
import time
import asyncio

from .backend import CentrifugeBackend
from pylabrobot import utils # might need to uses plates as resources

try:
  from pylibftdi import Device
  USE_FTDI = True
except ImportError:
  USE_FTDI = False


logger = logging.getLogger("pylabrobot")

class AgilentCentrifuge(CentrifugeBackend):
    """ A centrifuge backend for the Agilent Centrifuge. Note that this is not a complete implementation
  and many commands and parameters are not implemented yet. """

    def __init__(self):
        self.dev: Optional[Device] = None

    async def setup(self):
        if not USE_FTDI:
            raise RuntimeError("pylibftdi is not installed.")

        self.dev = Device()
        self.dev.open()
        print(self.dev, "open")

        for i in range(2):
            await self.setConfigurationData()
            await self.initialize()
        await self.setConfigurationData()
        await self.finishSetup()

    async def stop(self):
        await self.send(b"\xaa\x02\x0e\x10")
        await self.initialize()
        await self.setConfigurationData()
        if self.dev is not None:
            self.dev.close()

    async def read_resp(self, timeout=20) -> bytes:
        """ Read a response from the centrifuge. If the timeout is reached, return the data that has
    been read so far. """

        if self.dev is None:
            raise RuntimeError("device not initialized")

        d = b""
        last_read = b""
        end_byte_found = False
        t = time.time()
        
        while True:
            last_read = self.dev.read(25) # 25 is max length observed in pcap
            if len(last_read) > 0:
                d += last_read
                end_byte_found = d[-1] == 0x0d
                if len(last_read) < 25 and end_byte_found: # if we read less than 25 bytes, we're at the end
                    break
            else:
                # If we didn't read any data, check if the last read ended in an end byte. If so, we're done
                if end_byte_found:
                    break

                # Check if we've timed out.
                if time.time() - t > timeout:
                    logger.warning("timed out reading response")
                    break

                # If we read data, we don't wait and immediately try to read more.
                await asyncio.sleep(0.0001)

        logger.debug("read %s", d.hex())

        return d

    async def send(self, cmd: Union[bytearray, bytes], read_timeout = 1):
        """ Send a command to the centrifuge and return the response. """

        if self.dev is None:
            raise RuntimeError("Device not initialized")

        logger.debug("sending %s", cmd.hex())

        # w = self.dev.write(cmd)
        w = self.dev.write(cmd.decode('latin-1'))


        logger.debug("wrote %s bytes", w)

        assert w == len(cmd)

        resp = await self.read_resp(timeout=read_timeout)
        print(resp)
        return resp

    async def setConfigurationData(self): #TODO: see if firstconfiguration and second confirguration 
        self.dev.ftdi_fn.ftdi_set_latency_timer(16)
        self.dev.ftdi_fn.ftdi_set_line_property(8, 1, 0) # 8 bit size, 1 stop bit, no parity
        self.dev.ftdi_fn.ftdi_setflowctrl(0)
        self.dev.baudrate = 19200

    async def initialize(self):
        self.dev.write("\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
        for i in range(33):
            packet = b"\xaa"  # First byte is constant
            packet += bytes([i & 0xFF])  # Second byte increments
            packet += b"\x0e"  # Third byte is constant
            packet += bytes([0x0e + (i & 0xFF)])  # Fourth byte increments from 0x0e
            packet += bytes([0x00] * 8)  # Remaining 8 bytes are zeros
            self.dev.write(packet)

        packet = b""
        packet += b"\xaa\xff\x0f\x0e"
        await self.send(packet)

    async def finishSetup(self):
        await self.send(b"\xaa\x00\x21\x01\xff\x21")
        await self.send(b"\xaa\x01\x13\x20\x34")
        await self.send(b"\xaa\x00\x21\x02\xff\x22")
        await self.send(b"\xaa\x02\x13\x20\x35")
        await self.send(b"\xaa\x00\x21\x03\xff\x23") # expects NA
        await self.send(b"\xaa\xff\x1a\x14\x2d") # expects NA

        # not part of the status check: ftdi control
        self.dev.baudrate = 57700
        self.dev.ftdi_fn.ftdi_setrts(1)
        self.dev.ftdi_fn.ftdi_setdtr(1)

        await self.send(b"\xaa\x01\x0e\x0f") # expects 0909
        await self.send(b"\xaa\x02\x0e\x10") # expects 0000

        await self.send(b"\xaa\x01\x12\x1f\x32")
        for i in range(8):
            await self.send(b"\xaa\x02\x20\xff\x0f\x30")
        await self.send(b"\xaa\x02\x20\xdf\x0f\x10")
        await self.send(b"\xaa\x02\x20\xdf\x0e\x0f")
        await self.send(b"\xaa\x02\x20\xdf\x0c\x0d")
        await self.send(b"\xaa\x02\x20\xdf\x08\x09")
        for i in range(4):
            await self.send(b"\xaa\x02\x26\x00\x00\x28")
        await self.send(b"\xaa\x02\x12\x03\x17")
        for i in range(5):
            await self.send(b"\xaa\x02\x26\x20\x00\x48")
            await self.send(b"\xaa\x02\x0e\x10")
            await self.send(b"\xaa\x02\x26\x00\x00\x28")
            await self.send(b"\xaa\x02\x0e\x10")
        await self.send(b"\xaa\x02\x0e\x10")
        await self.send(b"\xaa\x02\x26\x00\x01\x29")
        await self.send(b"\xaa\x02\x0e\x10")

    async def openDoor(self):
        await self.send(b"\xaa\x02\x26\x00\x07\x2f")
        await self.send(b"\xaa\x02\x0e\x10")

    async def closeDoor(self):
        await self.send(b"\xaa\x02\x26\x00\x05\x2d")
        await self.send(b"\xaa\x02\x0e\x10")

    async def lockDoor(self): # lockDoor is overrided by openDoor
        await self.send(b"\xaa\x02\x26\x00\x01\x29")
        await self.send(b"\xaa\x02\x0e\x10")

    async def unlockDoor(self):
        await self.send(b"\xaa\x02\x26\x00\x05\x2d")
        await self.send(b"\xaa\x02\x0e\x10")



