# DTC Interface Testing

Install requirements.txt on first run through. 

## MacOS
```# 1. Navigate to your project folder
cd path/to/your/project

# 2. Create the virtual environment (named 'venv')
python3 -m venv venv

# 3. Activate the environment
source venv/bin/activate

# 4. Install the requirements
pip install -r requirements.txt
```

## Windows
```:: 1. Navigate to your project folder
cd path\to\your\project

:: 2. Create the virtual environment (named 'venv')
python -m venv venv

:: 3. Activate the environment
venv\Scripts\activate

:: 4. Install the requirements
pip install -r requirements.txt
```

## Running the tests
- Plug the DTC interface into the testing jig, once the firmware is downloaded on to it. 
- This program is intented to run using the default Modbus and SDI-12 settings.
- Plug the SDI-12 and Modbus converters into the computer. 
- Run the following command to execute the tests:

  ```python main.py```

- Ensure all temperatures and printed data look accurate. Temeprtares reading 99 degrees or 85 degrees, as well as parasitic power, will be flagged. 
- Watch the led test and ensure all LED colors are functioning properly.

