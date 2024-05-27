import logging
from typing import Optional, Union
import time
import asyncio

from .backend import CentrifugeBackend
from pylabrobot import utils

try:
    from pylibftdi import Device
    USE_FTDI = True
except ImportError:
    USE_FTDI = False

logger = logging.getLogger("pylabrobot")

class DoorOperationError(Exception):
    """Custom exception for door operation errors."""
    pass

class AgilentCentrifuge(CentrifugeBackend):
    """A centrifuge backend for the Agilent Centrifuge. Note that this is not a complete implementation
    and many commands and parameters are not implemented yet."""

    def __init__(self):
        self.dev: Optional[Device] = None
        self.door_status = False  # starts off closed
        self.lock_status = True   # starts off unlocked

    async def setup(self):
        if not USE_FTDI:
            raise RuntimeError("pylibftdi is not installed.")

        self.dev = Device()
        self.dev.open()
        print(self.dev, "open")

        for _ in range(2):
            await self._configure_and_initialize()

        await self._configure_and_initialize()
        await self.finish_setup()
        await self.unlock_door()

    async def stop(self):
        await self.send(b"\xaa\x02\x0e\x10")
        await self._configure_and_initialize()
        if self.dev:
            self.dev.close()

    async def read_resp(self, timeout=20) -> bytes:
        """Read a response from the centrifuge. If the timeout is reached, return the data that has
        been read so far."""
        if not self.dev:
            raise RuntimeError("Device not initialized")

        data = b""
        end_byte_found = False
        start_time = time.time()

        while True:
            chunk = self.dev.read(25)
            if chunk:
                data += chunk
                end_byte_found = data[-1] == 0x0d
                if len(chunk) < 25 and end_byte_found:
                    break
            else:
                if end_byte_found or time.time() - start_time > timeout:
                    logger.warning("Timed out reading response")
                    break
                await asyncio.sleep(0.0001)

        logger.debug("Read %s", data.hex())
        return data

    async def send(self, cmd: Union[bytearray, bytes], read_timeout=0.4) -> bytes:
        """Send a command to the centrifuge and return the response."""
        if not self.dev:
            raise RuntimeError("Device not initialized")

        logger.debug("Sending %s", cmd.hex())
        written = self.dev.write(cmd.decode('latin-1'))
        logger.debug("Wrote %s bytes", written)

        if written != len(cmd):
            raise RuntimeError("Failed to write all bytes")
        resp = await self.read_resp(timeout=read_timeout)
        print(resp)
        return resp

    async def _configure_and_initialize(self):
        await self.set_configuration_data()
        await self.initialize()

    async def set_configuration_data(self):
        """Set the device configuration data."""
        self.dev.ftdi_fn.ftdi_set_latency_timer(16)
        self.dev.ftdi_fn.ftdi_set_line_property(8, 1, 0)
        self.dev.ftdi_fn.ftdi_setflowctrl(0)
        self.dev.baudrate = 19200

    async def initialize(self):
        """Initialize the device."""
        self.dev.write(b"\x00" * 20)
        for i in range(33):
            packet = b"\xaa" + bytes([i & 0xFF, 0x0e, 0x0e + (i & 0xFF)]) + b"\x00" * 8
            self.dev.write(packet)
        await self.send(b"\xaa\xff\x0f\x0e")

    async def finish_setup(self):
        """Finish the setup process."""
        await self.send(b"\xaa\x00\x21\x01\xff\x21")
        await self.send(b"\xaa\x01\x13\x20\x34")
        await self.send(b"\xaa\x00\x21\x02\xff\x22")
        await self.send(b"\xaa\x02\x13\x20\x35")
        await self.send(b"\xaa\x00\x21\x03\xff\x23")
        await self.send(b"\xaa\xff\x1a\x14\x2d")

        self.dev.baudrate = 57700
        self.dev.ftdi_fn.ftdi_setrts(1)
        self.dev.ftdi_fn.ftdi_setdtr(1)

        await self.send(b"\xaa\x01\x0e\x0f")
        await self.send(b"\xaa\x02\x0e\x10")
        await self.send(b"\xaa\x01\x12\x1f\x32")
        for _ in range(8):
            await self.send(b"\xaa\x02\x20\xff\x0f\x30")
        await self.send(b"\xaa\x02\x20\xdf\x0f\x10")
        await self.send(b"\xaa\x02\x20\xdf\x0e\x0f")
        await self.send(b"\xaa\x02\x20\xdf\x0c\x0d")
        await self.send(b"\xaa\x02\x20\xdf\x08\x09")
        for _ in range(4):
            await self.send(b"\xaa\x02\x26\x00\x00\x28")
        await self.send(b"\xaa\x02\x12\x03\x17")
        for _ in range(5):
            await self.send(b"\xaa\x02\x26\x20\x00\x48")
            await self.send(b"\xaa\x02\x0e\x10")
            await self.send(b"\xaa\x02\x26\x00\x00\x28")
            await self.send(b"\xaa\x02\x0e\x10")
        await self.send(b"\xaa\x02\x0e\x10")
        await self.send(b"\xaa\x02\x26\x00\x01\x29")
        await self.send(b"\xaa\x02\x0e\x10")

    async def open_door(self):
        if await self.is_locked():
            raise DoorOperationError("Door is locked")
        if await self.is_open():
            raise DoorOperationError("Door is already opened")
        
        try:
            await self.send(b"\xaa\x02\x26\x00\x07\x2f")
            await self.send(b"\xaa\x02\x0e\x10")
            self.door_status = True
        except Exception as e:
            logger.error(f"Failed to send command to open door: {e}")
            raise

    async def close_door(self):
        if await self.is_locked():
            raise DoorOperationError("Door is locked")
        if not await self.is_open():
            raise DoorOperationError("Door is already closed")
        
        try:
            await self.send(b"\xaa\x02\x26\x00\x05\x2d")
            await self.send(b"\xaa\x02\x0e\x10")
            self.door_status = False
        except Exception as e:
            logger.error(f"Failed to send command to close door: {e}")
            raise

    async def is_open(self) -> bool:
        return self.door_status

    async def lock_door(self):
        await self.send(b"\xaa\x02\x26\x00\x01\x29")
        await self.send(b"\xaa\x02\x0e\x10")
        self.lock_status = True

    async def unlock_door(self):
        await self.send(b"\xaa\x02\x26\x00\x05\x2d")
        await self.send(b"\xaa\x02\x0e\x10")
        self.lock_status = False

    async def is_locked(self) -> bool:
        return self.lock_status
