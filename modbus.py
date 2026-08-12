import time
import serial
import modbus_tk
import modbus_tk.defines as cst
from modbus_tk import modbus_rtu

def run_modbus_test(port, slave_id=1):
    error = 0
    print(f"[Modbus] Starting on {port}...")
    
    try:
        ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=2.0
        )
        
        master = modbus_rtu.RtuMaster(ser)
        master.set_timeout(2.0)
        
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        # --- STEP 1: Read the sensor count at register 0 ---
        #print("[Modbus Query 1/2] Fetching active sensor count from register 0...")
        count_response = master.execute(slave_id, cst.READ_INPUT_REGISTERS, 0, 1)
        
        if not count_response:
            print("[Modbus Error] Empty response received for active sensor count.")
            return
            
        active_count = count_response[0]
        print(f"[Modbus Log] Found {active_count} active temperature sensors.")
        
        if active_count == 0:
            print("[Modbus Warning] Active sensor count is 0.")
            return
            
        # Bound check to avoid exceeding device limits (max 125 registers)
        if active_count > 125:
            print(f"[Modbus Warning] Count ({active_count}) exceeds safety limit. Capping at 125.")
            active_count = 125

        # --- STEP 2: Dynamically read all active temperature registers ---
        # Starting at address 1, read exactly 'active_count' registers
        #print(f"[Modbus Query 2/2] Requesting {active_count} registers from address 1...")
        temp_response = master.execute(slave_id, cst.READ_INPUT_REGISTERS, 1, active_count)
        
        #print(f"[Modbus SUCCESS] Raw payload data received -> {temp_response}")
        print("\n" + "="*45)
        print("         --- Modbus Temperatures ---       ")
        print("="*45)
        
        # Loop through the dynamic response payload
        for i in range(len(temp_response)):
            register_address = 1 + i
            raw_temp = temp_response[i]
            
            # Format negative temperatures if your device uses 16-bit signed integers (Two's Complement)
            if raw_temp > 32767:
                raw_temp -= 65536

            if raw_temp == 9900:
                print(f"  -> Sensor #{i+1} [Reg {register_address}]: [ERROR]")
                error = error + 1
            scaled_temp = raw_temp / 100.0
            print(f"  -> Sensor #{i+1} : {scaled_temp}°C")
            
        #print("[Modbus SUCCESS] Dynamic temperature sweep completed cleanly.")
            
    except Exception as e:
        print(f"[Modbus ERROR] Transaction failed: {e}")
        
    print(f"[Modbus] Total errors found: {error}")
    if error > 0:
        return False
    else: 
        return True
