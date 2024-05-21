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
            raise RuntimeError("to do")

        self.dev = Device()
        self.dev.open()
        print(self.dev, "open")

        await self.firstInit()
        await self.initialize()
        await self.secondInit()
        await self.initialize()
        await self.secondInit()
        await self.sendsix()
        await self.firstInit()
        await self.initialize()
        await self.secondInit()
        await self.initialize()
        await self.secondInit()
        await self.sendsix()
        await self.firstInit()
        await self.initialize()

        # await self.request_eeprom_data() # TODO: write request eeprom data()

    async def getModemStat(self):
        bmRequestType = 0xC0
        bRequest = 0x05
        wValue = 0
        wIndex = 0
        wLength = 2

        response = self.dev.ctrl_transfer(bmRequestType, bRequest, wValue, wIndex, wLength)

        if len(response) == 2:
            modem_status = response[0] | (response[1] << 8)
            print(f"Modem status: {modem_status}")
        else:
            print("Unexpected response lenght.")

    async def stop(self):
        if self.dev is not None:
            self.dev.close()

    async def read_resp(self, timeout=20) -> bytes:
        """ Read a response from the centrifuge. """

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

    async def send(self, cmd: Union[bytearray, bytes], read_timeout=0.5):
        """ Send a command to the centrifuge and return the response. """

        if self.dev is None:
            raise RuntimeError("Device not initialized")

        logger.debug("sending %s", cmd.hex())

        # w = self.dev.write(cmd)
        w = self.dev.write(cmd.decode('latin-1'))


        logger.debug("wrote %s bytes", w)

        assert w == len(cmd)

        resp = await self.read_resp(timeout=read_timeout)
        return resp

    async def firstInit(self):
        self.dev.ftdi_fn.ftdi_usb_purge_buffers()
        self.dev.ftdi_fn.ftdi_usb_purge_buffers()
        self.dev.ftdi_fn.ftdi_usb_reset()

        # reset USB pipe and clear any stalls on the USB pipe
        # endpoint_address = 0x81
        # direction = 'IN'

        # self.dev.usb_dev.reset_endpoint(endpoint_address, direction)
        # self.dev.usb_dev.clear_halt(endpoint_address)

        #set lat timer
        self.dev.ftdi_fn.ftdi_set_latency_timer(16)
        self.dev.read(64)

        # await self.getModemStat()

        self.dev.ftdi_fn.ftdi_set_line_property(8, 1, 0) # 8 bit size, 1 stop bit, no parity
        self.dev.ftdi_fn.ftdi_setdtr(True)

        self.dev.ftdi_fn.ftdi_setrts(True)

        self.dev.ftdi_fn.ftdi_setflowctrl(0)
        self.dev.baudrate = 19200

        self.dev.ftdi_fn.ftdi_setrts(True)
        self.dev.ftdi_fn.ftdi_setdtr(True)

        self.dev.ftdi_fn.ftdi_set_line_property(8, 1, 0) # 8 bit size, 1 stop bit, no parity
        self.dev.ftdi_fn.ftdi_setflowctrl(0)

    async def secondInit(self):
        self.dev.baudrate = 19200

        self.dev.ftdi_fn.ftdi_setrts(True)
        self.dev.ftdi_fn.ftdi_setdtr(True)

        self.dev.ftdi_fn.ftdi_set_line_property(8, 1, 0) # 8 bit size, 1 stop bit, no parity
        self.dev.ftdi_fn.ftdi_setflowctrl(0)

    async def initialize(self):
        for i in range(33):
            packet = b"\xaa"  # First byte is constant
            packet += bytes([i & 0xFF])  # Second byte increments
            packet += b"\x0e"  # Third byte is constant
            packet += bytes([0x0e + (i & 0xFF)])  # Fourth byte increments from 0x0e
            packet += bytes([0x00] * 8)  # Remaining 8 bytes are zeros
            self.dev.write(packet)

        packet = b""
        packet += b"\xaa\xff\x0f\x0e"
        check = await self.send(packet)
        if check == 0x89:
            print("Initialization succesful")

    async def sendsix(self):
        await self.send(b"\xaa\x00\x21\x01\xff\x21")

