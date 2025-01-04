# Leviton Load Center Local API Access Guide
*A guide to enabling local API access on Leviton LDATA devices*

## Overview
This guide explains how to enable local HTTP API access on Leviton LDATA devices. By default, this capability is disabled and requires physical modification to enable. The process involves adding a serial header to access the device's bootloader and creating a configuration file.

**Warning**: This modification will void your warranty and carries a risk of damaging your device. Proceed at your own risk.

## Required Materials

### Hardware
- USB to TTL serial adapter (e.g., [CP2102 adapter](https://www.amazon.com/gp/product/B07BBPX8B8))
- Soldering iron with fine tip
- Solder
- 6-pin headers
- [2-pole polarized plug](https://www.homedepot.com/p/Leviton-15-Amp-125-Volt-2-Pole-2-Wire-Polarized-Plug-White-R62-00101-0WH/302183191) (recommended)
- Extension cord or power strip with on/off switch

### Software
- Terminal program (e.g., Tera Term, minicom)

## Step-by-Step Instructions

### 1. Disassembly
1. Remove LDATA from electrical panel
2. Remove exterior screws to access circuit board
3. Note the black gasket between halves
4. Optionally remove WiFi antenna for easier access
5. Remove silicon from rear connector for better wire access

### 2. Adding Serial Header
1. Locate the J3 6-pin header holes in upper right corner
2. Solder 6-pin header from rear of board 
3. Record WiFi and Ethernet MAC addresses from sticker
4. Note: Pin 0 has square pad (bottom pin)

### 3. Initial Serial Connection
1. Connect polarized plug to LDATA power wires
2. Configure terminal program:
   - 115200 baud
   - 8 data bits
   - No parity
   - 1 stop bit
3. Connect USB-TTL adapter:
   - Ground → Pin 0 
   - TX → Pin 3
   - RX → Pin 4

### 4. Testing Connection
1. Power on LDATA
2. Verify bootloader output appears:
```
U-Boot SPL 2015.10-mx6ul+g570b452 (Mar 25 2018 - 12:39:27)
i.MX6UL SOC
...
```
3. If no output, try swapping TX/RX connections

### 5. Accessing U-Boot
1. Power off LDATA
2. Press space bar while powering on
3. Should see `MX6UL_VAR_DART(mmc)==>`
4. If Linux starts booting, try again

### 6. Identifying Partitions
1. Run `printenv` to find mmcdev and mmcpart values
2. Run `mmc dev X` (X = mmcdev number)
3. Run `mmc part` to list partitions
4. Note data partition (usually partition 3)

### 7. Creating API Configuration File
1. Run `printenv` to get loadaddr and loadimagesize
2. Zero memory: `mw.b 0x82000000 0 6300000`
3. Write "true" to memory:
```
mw.b 0x82000000 0x74
mw.b 0x82000001 0x72
mw.b 0x82000002 0x75
mw.b 0x82000003 0x65
mw.b 0x82000004 0x0a
```
4. Create file: `ext4write mmc 1:3 0x82000000 /HTTP_API_ALWAYS_ON 5`
5. Verify with `ext4ls mmc 1:3`

### 8. Network Configuration
1. Set static DHCP reservation for LDATA
2. Connect Ethernet cable if using wired connection

### 9. Testing API Access
1. Reset device: `reset`
2. Wait for boot messages
3. Look for API port number (default: 13107)
4. Test in browser: `http://<ip-address>:13107/api`
5. Should receive: `{ "message": "hooray! welcome to our api!" }`

### 10. Reassembly
1. Reverse disassembly steps
2. Optionally cut access hole for serial header
3. Reinstall in electrical panel

## API Endpoints

### Device Information
```
GET http://<ip>:<port>/api/residentialBreakerPanels/<LDATA-ID>/
```

### Breaker Status
```
GET http://<ip>:<port>/api/residentialBreakerPanels/<LDATA-ID>/residentialBreakers
```

### Manual Breaker Control
```
POST http://<ip>:<port>/api/residentialBreakers/<BREAKER-MAC>/trip
```

### WiFi Management
```
GET http://<ip>:<port>/api/residentialBreakerPanels/<LDATA-ID>/wifiSSIDs
GET http://<ip>:<port>/api/residentialBreakerPanels/<LDATA-ID>/wifiSSIDsWithRSSI
POST http://<ip>:<port>/api/residentialBreakerPanels/<LDATA-ID>/wifiConnect
POST http://<ip>:<port>/api/residentialBreakerPanels/<LDATA-ID>/wifiDisable
```

## Troubleshooting

### Identifying Data Partition
If unsure which partition is the data partition:
1. Use `ext4ls mmc 1:X` on each partition
2. Data partition contains:
   - node-lfa-client directory
   - snapshots directory
   - ncm.log file
   - .rbpconfig files

### Common Issues
- No serial output: Check TX/RX connections and serial settings
- API not responding: Verify IP address, port number, and HTTP (not HTTPS)
- Boot interruption timing: Must press space bar immediately after power-on

## References
- Contributed by STUNTPENIS (Reddit)
- https://www.reddit.com/r/smarthome/comments/1gc8g9r/leviton_load_center_local_access_to_data_and/
- date: January 2024
