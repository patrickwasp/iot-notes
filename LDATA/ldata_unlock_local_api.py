#!/usr/bin/env python3
"""
LDATA Serial Modification Tool
This script safely applies modifications to enable local API access on Leviton LDATA devices.
"""

import sys
import time
import logging
import serial
import serial.tools.list_ports
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict
import json
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint
import backoff

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ldata_modifier.log'),
        logging.StreamHandler()
    ]
)

console = Console()

@dataclass
class LDATADevice:
    serial_port: str
    device_id: Optional[str] = None
    mac_addresses: Dict[str, str] = None
    data_partition: Optional[int] = None
    api_enabled: bool = False

class LDATAModifier:
    def __init__(self):
        self.device = None
        self.serial = None
        self.backup_dir = Path('ldata_backups')
        self.backup_dir.mkdir(exist_ok=True)
        
    def detect_serial_ports(self) -> List[str]:
        """Detect available serial ports."""
        ports = list(serial.tools.list_ports.comports())
        return [port.device for port in ports]

    @backoff.on_exception(backoff.expo, serial.SerialException, max_tries=3)
    def connect_serial(self, port: str, baudrate: int = 115200) -> None:
        """Connect to serial port with retry capability."""
        try:
            self.serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1
            )
            logging.info(f"Successfully connected to {port}")
        except serial.SerialException as e:
            logging.error(f"Failed to connect to {port}: {str(e)}")
            raise

    def backup_device_state(self) -> None:
        """Create backup of current device state."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"backup_{timestamp}"
        backup_path.mkdir(exist_ok=True)
        
        # Save current configuration
        if self.device.device_id:
            with open(backup_path / "device_info.json", 'w') as f:
                json.dump({
                    'device_id': self.device.device_id,
                    'mac_addresses': self.device.mac_addresses,
                    'data_partition': self.device.data_partition
                }, f, indent=2)
        
        logging.info(f"Created backup at {backup_path}")

    def wait_for_bootloader(self, timeout: int = 30) -> bool:
        """Wait for U-Boot bootloader prompt."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task("Waiting for bootloader...", total=timeout)
            
            start_time = time.time()
            buffer = ""
            
            while (time.time() - start_time) < timeout:
                if self.serial.in_waiting:
                    char = self.serial.read().decode('utf-8', errors='ignore')
                    buffer += char
                    if "MX6UL_VAR_DART(mmc)==>" in buffer:
                        return True
                progress.update(task, advance=1)
                
            return False

    def identify_data_partition(self) -> Optional[int]:
        """Identify the data partition through analysis of partition table."""
        self.serial.write(b"printenv\n")
        time.sleep(1)
        
        # Parse output for mmcdev
        output = self.serial.read_all().decode('utf-8', errors='ignore')
        
        try:
            # Extract mmcdev number
            for line in output.split('\n'):
                if 'mmcdev=' in line:
                    mmcdev = line.split('=')[1].strip()
                    break
            else:
                raise ValueError("Could not find mmcdev in output")

            # Get partition table
            self.serial.write(f"mmc dev {mmcdev}\n".encode())
            time.sleep(0.5)
            self.serial.write(b"mmc part\n")
            time.sleep(1)
            
            part_output = self.serial.read_all().decode('utf-8', errors='ignore')
            
            # Find data partition (usually the largest partition)
            max_size = 0
            data_part = None
            
            for line in part_output.split('\n'):
                if line.strip() and line[0].isdigit():
                    parts = line.split()
                    if len(parts) >= 3:
                        size = int(parts[2])
                        if size > max_size:
                            max_size = size
                            data_part = int(parts[0])
            
            return data_part
            
        except Exception as e:
            logging.error(f"Error identifying data partition: {str(e)}")
            return None

    def enable_api_access(self) -> bool:
        """Enable API access by creating necessary configuration file."""
        try:
            # Zero out memory
            self.serial.write(b"mw.b 0x82000000 0 6300000\n")
            time.sleep(1)
            
            # Write "true" to memory
            commands = [
                b"mw.b 0x82000000 0x74\n",  # t
                b"mw.b 0x82000001 0x72\n",  # r
                b"mw.b 0x82000002 0x75\n",  # u
                b"mw.b 0x82000003 0x65\n",  # e
                b"mw.b 0x82000004 0x0a\n"   # newline
            ]
            
            for cmd in commands:
                self.serial.write(cmd)
                time.sleep(0.2)
            
            # Verify memory contents
            self.serial.write(b"md.b 0x82000000 0x5\n")
            time.sleep(1)
            output = self.serial.read_all().decode('utf-8', errors='ignore')
            
            if not all(x in output for x in ['74', '72', '75', '65']):
                raise ValueError("Memory verification failed")
            
            # Write to filesystem
            if self.device.data_partition:
                cmd = f"ext4write mmc 1:{self.device.data_partition} 0x82000000 /HTTP_API_ALWAYS_ON 5\n"
                self.serial.write(cmd.encode())
                time.sleep(1)
                
                # Verify file creation
                self.serial.write(f"ext4ls mmc 1:{self.device.data_partition}\n".encode())
                time.sleep(1)
                output = self.serial.read_all().decode('utf-8', errors='ignore')
                
                if 'HTTP_API_ALWAYS_ON' in output:
                    self.device.api_enabled = True
                    return True
                    
            return False
            
        except Exception as e:
            logging.error(f"Error enabling API access: {str(e)}")
            return False

    def verify_modifications(self) -> bool:
        """Verify all modifications were applied correctly."""
        try:
            if not self.device.api_enabled:
                return False
                
            # Reset device
            self.serial.write(b"reset\n")
            time.sleep(5)  # Wait for reboot
            
            # Look for API startup message
            timeout = 60
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                if self.serial.in_waiting:
                    output = self.serial.read_all().decode('utf-8', errors='ignore')
                    if "HTTP API server started on port" in output:
                        return True
                time.sleep(1)
                
            return False
            
        except Exception as e:
            logging.error(f"Error verifying modifications: {str(e)}")
            return False

    def run(self):
        """Main execution flow."""
        try:
            with console.status("[bold green]Initializing...") as status:
                # Detect available ports
                ports = self.detect_serial_ports()
                if not ports:
                    rprint("[red]No serial ports detected!")
                    return
                
                # Let user select port
                port = Prompt.ask(
                    "Select serial port",
                    choices=ports,
                    default=ports[0] if ports else None
                )
                
                # Create device instance
                self.device = LDATADevice(serial_port=port)
                
                # Connect to serial port
                status.update("[bold yellow]Connecting to serial port...")
                self.connect_serial(port)
                
                # Create backup
                status.update("[bold yellow]Creating backup...")
                self.backup_device_state()
                
                # Check if already modified
                status.update("[bold yellow]Checking current state...")
                self.device.data_partition = self.identify_data_partition()
                
                if not self.device.data_partition:
                    rprint("[red]Could not identify data partition!")
                    return
                
                # Prompt for physical access if needed
                if not self.wait_for_bootloader():
                    if not Confirm.ask("Please ensure you have physical access to the device. Ready to continue?"):
                        return
                        
                    rprint("[yellow]Power cycle the device and immediately press SPACE when prompted...")
                    if not self.wait_for_bootloader(timeout=60):
                        rprint("[red]Failed to access bootloader!")
                        return
                
                # Enable API access
                status.update("[bold yellow]Enabling API access...")
                if not self.enable_api_access():
                    rprint("[red]Failed to enable API access!")
                    return
                
                # Verify modifications
                status.update("[bold yellow]Verifying modifications...")
                if self.verify_modifications():
                    rprint("[green]Successfully enabled API access!")
                else:
                    rprint("[red]Verification failed - please check logs!")
                
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
            rprint(f"[red]An unexpected error occurred: {str(e)}")
            
        finally:
            if self.serial and self.serial.is_open:
                self.serial.close()

if __name__ == "__main__":
    modifier = LDATAModifier()
    modifier.run()
