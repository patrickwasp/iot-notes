import requests
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Set
import json
import socket
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

@dataclass
class BreakerInfo:
    id: str  # MAC address
    average_current: float
    branch_type: str
    current_rating: int
    current_state: str
    energy_consumption: float
    line_frequency: float
    manufacturer: str
    model: str
    name: str
    position: int
    power: float
    rms_current: float
    rms_voltage: float
    serial_number: str

@dataclass
class PanelInfo:
    id: str
    breaker_count: int
    commissioned: bool
    manufacturer: str
    model: str
    name: str
    package_ver: str
    panel_size: int
    version_bcm: str
    version_bsm: str
    version_ncm: str

@dataclass
class WifiNetwork:
    ssid: str
    signal_strength: Optional[float] = None

class LDATADeviceInfo:
    """Information about a discovered LDATA device"""
    def __init__(self, ip: str, panel_id: str, port: int = 13107):
        self.ip = ip
        self.panel_id = panel_id
        self.port = port

    def __str__(self):
        return f"LDATA Device {self.panel_id} at {self.ip}:{self.port}"

class LDATAClient:
    """Client for interacting with LDATA device API"""
    
    @staticmethod
    def discover_devices(network: str = "192.168.1.0/24", port: int = 13107, timeout: float = 0.5) -> List[LDATADeviceInfo]:
        """
        Discover LDATA devices on the network
        
        Args:
            network: Network CIDR to scan (e.g., "192.168.1.0/24")
            port: Port to scan for LDATA API (default: 13107)
            timeout: Timeout for each connection attempt in seconds
            
        Returns:
            List of discovered LDATA devices
        """
        def check_host(ip: str) -> Optional[LDATADeviceInfo]:
            try:
                # Try to connect to the API endpoint
                url = f"http://{ip}:{port}/api"
                response = requests.get(url, timeout=timeout)
                
                # If we get a response, try to get the panel ID
                if response.status_code == 200:
                    # The panel ID will be in any panel-specific response
                    # Try the wifi SSIDs endpoint as it's lightweight
                    panels_url = f"{url}/residentialBreakerPanels"
                    panels_response = requests.get(panels_url, timeout=timeout)
                    
                    if panels_response.status_code == 200:
                        panels_data = panels_response.json()
                        # The response format might vary, but we expect the panel ID
                        # to be available in some form
                        if isinstance(panels_data, list) and len(panels_data) > 0:
                            panel_id = panels_data[0].get('id')
                            if panel_id and panel_id.startswith('LDATA-'):
                                return LDATADeviceInfo(ip, panel_id, port)
                        
            except (requests.RequestException, json.JSONDecodeError, KeyError):
                pass
            return None

        # Generate list of IP addresses to scan
        network = ipaddress.ip_network(network)
        ips = [str(ip) for ip in network.hosts()]
        
        # Scan network with thread pool
        discovered_devices = []
        with ThreadPoolExecutor(max_workers=50) as executor:
            for device in executor.map(check_host, ips):
                if device:
                    discovered_devices.append(device)
                    
        return discovered_devices
    
    def __init__(self, host: str, port: int = 13107):
        """
        Initialize LDATA client
        
        Args:
            host: IP address or hostname of LDATA device
            port: API port number (default 13107)
        """
        self.base_url = f"http://{host}:{port}/api"
        
    def _get(self, endpoint: str) -> Dict[str, Any]:
        """Make GET request to API endpoint"""
        response = requests.get(f"{self.base_url}/{endpoint}")
        response.raise_for_status()
        return response.json()
        
    def _post(self, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make POST request to API endpoint"""
        response = requests.post(f"{self.base_url}/{endpoint}", data=data)
        response.raise_for_status()
        return response.json()

    def get_panel_info(self, panel_id: str) -> PanelInfo:
        """
        Get information about a specific panel
        
        Args:
            panel_id: LDATA panel ID (format: LDATA-XXXXX-XXXXX-XXXXX)
            
        Returns:
            PanelInfo object containing panel details
        """
        data = self._get(f"residentialBreakerPanels/{panel_id}")
        return PanelInfo(
            id=data["id"],
            breaker_count=data["breakerCount"],
            commissioned=data["commissioned"],
            manufacturer=data["manufacturer"],
            model=data["model"],
            name=data["name"],
            package_ver=data["packageVer"],
            panel_size=data["panelSize"],
            version_bcm=data["versionBCM"],
            version_bsm=data["versionBSM"],
            version_ncm=data["versionNCM"]
        )

    def get_breakers(self, panel_id: str) -> List[BreakerInfo]:
        """
        Get information about all breakers in a panel
        
        Args:
            panel_id: LDATA panel ID
            
        Returns:
            List of BreakerInfo objects containing breaker details
        """
        data = self._get(f"residentialBreakerPanels/{panel_id}/residentialBreakers")
        return [
            BreakerInfo(
                id=breaker["id"],
                average_current=breaker["averageCurrent"],
                branch_type=breaker["branchType"],
                current_rating=breaker["currentRating"],
                current_state=breaker["currentState"],
                energy_consumption=breaker["energyConsumption"],
                line_frequency=breaker["lineFrequency"],
                manufacturer=breaker["manufacturer"],
                model=breaker["model"],
                name=breaker["name"],
                position=breaker["position"],
                power=breaker["power"],
                rms_current=breaker["rmsCurrent"],
                rms_voltage=breaker["rmsVoltage"],
                serial_number=breaker["serialNumber"]
            )
            for breaker in data
        ]

    def trip_breaker(self, breaker_id: str) -> bool:
        """
        Manually trip a specific breaker
        
        Args:
            breaker_id: MAC address of breaker
            
        Returns:
            True if successful, False otherwise
        """
        response = self._get(f"residentialBreakers/{breaker_id}/trip")
        return response["messageType"] == "ACK"

    def get_wifi_networks(self, panel_id: str, include_signal_strength: bool = False) -> List[WifiNetwork]:
        """
        Get list of available WiFi networks
        
        Args:
            panel_id: LDATA panel ID
            include_signal_strength: Whether to include signal strength info
            
        Returns:
            List of WifiNetwork objects
        """
        endpoint = f"residentialBreakerPanels/{panel_id}/{'wifiSSIDsWithRSSI' if include_signal_strength else 'wifiSSIDs'}"
        data = self._get(endpoint)
        
        networks = []
        if include_signal_strength:
            for network in data["ssids"]:
                networks.append(WifiNetwork(
                    ssid=network["ssid"],
                    signal_strength=network["signalStrength"]
                ))
        else:
            networks = [WifiNetwork(ssid=ssid) for ssid in data["ssids"]]
            
        return networks

    def connect_wifi(self, panel_id: str, ssid: str, passphrase: str) -> bool:
        """
        Connect to a WiFi network
        
        Args:
            panel_id: LDATA panel ID
            ssid: Network SSID
            passphrase: Network password
            
        Returns:
            True if successful, False otherwise
        """
        data = {
            "ssid": ssid,
            "passphrase": passphrase
        }
        response = self._post(f"residentialBreakerPanels/{panel_id}/wifiConnect", data)
        return response["messageType"] == "ACK"

    def disconnect_wifi(self, panel_id: str) -> bool:
        """
        Disconnect from current WiFi network
        
        Args:
            panel_id: LDATA panel ID
            
        Returns:
            True if successful, False otherwise
        """
        response = self._post(f"residentialBreakerPanels/{panel_id}/wifiDisable")
        return response["messageType"] == "ACK"

# Example usage:
if __name__ == "__main__":
    # Discover LDATA devices on the network
    print("Discovering LDATA devices...")
    devices = LDATAClient.discover_devices()
    
    if not devices:
        print("No LDATA devices found on the network")
        exit(1)
        
    # Use the first discovered device
    device = devices[0]
    print(f"Found device: {device}")
    
    # Initialize client with discovered device
    client = LDATAClient(device.ip, device.port)
    PANEL_ID = device.panel_id
    
    # Get panel info
    panel = client.get_panel_info(PANEL_ID)
    print(f"Panel {panel.name}: {panel.breaker_count} breakers")
    
    # Get breaker info
    breakers = client.get_breakers(PANEL_ID)
    for breaker in breakers:
        print(f"Breaker {breaker.name}: {breaker.power}W")
    
    # Get WiFi networks with signal strength
    networks = client.get_wifi_networks(PANEL_ID, include_signal_strength=True)
    for network in networks:
        print(f"Network {network.ssid}: {network.signal_strength}dBm")
