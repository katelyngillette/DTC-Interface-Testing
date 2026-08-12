import time
import serial
import re

def parse_concurrent_delay(response_str):
    # Parses layout: a00099 (Address + 3 digits wait time + digits for count)
    match = re.match(r"^.{1}(\d{3})(\d+)", response_str)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0

def extract_values(response_str):
    if not response_str or len(response_str) <= 1:
        return []
    pattern = r"([+-]\d*\.?\d+)"
    return [float(val) for val in re.findall(pattern, response_str[1:])]

def collect_data_slice(ser, sensor_address, total_expected):
    collected = []
    current_data_index = 0
    while len(collected) < total_expected and current_data_index <= 9:
        d_cmd = f"{sensor_address}D{current_data_index}!\r\n"
        ser.write(d_cmd.encode('ascii'))
        ser.flush()
        time.sleep(0.15)
        d_response = ser.read_until(b'\n').decode('ascii', errors='ignore').strip()
        if not d_response:
            break
        new_vals = extract_values(d_response)
        if not new_vals:
            break
        collected.extend(new_vals)
        current_data_index += 1
    return collected

def run_sdi12_test(port, sensor_address='0'):
    print(f"[SDI-12] Starting on {port}...")
    error = 0
    all_collected_values = []
    try:
        with serial.Serial(port=port, baudrate=9600, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=3.0) as ser:
            ser.dtr = True
            ser.rts = True
            time.sleep(0.5)
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # -----------------------------------------------------------------
            # EXECUTE MEASUREMENT GROUP 0 (0C!)
            # -----------------------------------------------------------------
            command_str = f"{sensor_address}C!\r\n"
            ser.write(command_str.encode('ascii'))
            ser.flush()
            time.sleep(0.2)
            c_response = ser.read_until(b'\n').decode('ascii', errors='ignore').strip()
            print(f"[SDI-12] 0C! Response -> {c_response}")
            
            wait_time, total_expected = parse_concurrent_delay(c_response)
            if c_response and total_expected > 0:
                if wait_time > 0:
                    print(f"[SDI-12] Waiting {wait_time}s for compilation...")
                    time.sleep(wait_time)
                pass1_values = collect_data_slice(ser, sensor_address, total_expected)
                all_collected_values.extend(pass1_values)


            # Give the sensor a full second to clear its internal measurement state
            time.sleep(1.0) 
            
            ser.reset_input_buffer() 
            ser.reset_output_buffer()

            # HARDWARE WAKEUP & LINE STATE FORCING
            ser.dtr = False
            ser.rts = False
            time.sleep(0.05)
            ser.dtr = True
            ser.rts = True
            time.sleep(0.1)

            ser.break_condition = True   # Assert break condition
            time.sleep(0.020)             # Hold for 20ms (well over 12ms minimum)
            ser.break_condition = False  # Release break condition
            time.sleep(0.015)             # Marking state buffer window (over 8.33ms minimum)

            # Run 0C1! if the initial response indicated more than 99 values
            if (c_response == '000099'):
                command_str = f"{sensor_address}C1!\r\n"
                ser.write(command_str.encode('ascii'))
                ser.flush()
                
                # Increase read timeout temporarily for this specific read to capture slow responses
                original_timeout = ser.timeout
                ser.timeout = 5.0 
                
                c1_response = ser.read_until(b'\n').decode('ascii', errors='ignore').strip()
                print(f"[SDI-12] 0C1! Response -> {c1_response}")
                
                # Restore original timeout configuration
                ser.timeout = original_timeout


            
                wait_time1, total_expected1 = parse_concurrent_delay(c1_response)
                if c1_response and total_expected1 > 0:
                    if wait_time1 > 0:
                        print(f"[SDI-12] Waiting {wait_time1}s for compilation...")
                        time.sleep(wait_time1)
                    
                    pass2_values = collect_data_slice(ser, sensor_address, total_expected1)
                    all_collected_values.extend(pass2_values)

            # -----------------------------------------------------------------
            # FORMATTING Temperatures
            # -----------------------------------------------------------------
            if not all_collected_values:
                print("\n[SDI-12] No metrics were successfully parsed from the registers.")
                return
            
            print("\n" + "="*45)
            print("         --- SDI-12 Temperatures ---       ")
            print("="*45)
            for index, val in enumerate(all_collected_values):
                if val == 99.00 or val == 85.00 or val == -999:
                    print(f" -> Sensor #{index + 1} : {val:.2f}: [ERROR]")
                    error = error + 1
                else:
                    print(f" -> Sensor #{index + 1} : {val:.2f}")
            print("="*45)

            # Final Summary
            if (error > 0):
                print(f"[SDI-12] {error} total errors detected during.")
                return False
            else:
                print(f"[SDI-12] Total errors detected: {error}.")
                return True
            
    except Exception as e:
        print(f"[SDI-12 ERROR] {e}")
  
