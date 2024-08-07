import serial
import utils
import numpy as np
from gantry import Gantry
from enum import Enum
from datetime import datetime
from kalman_filter import KalmanFilter
import matplotlib.pyplot as plt
import pickle
from time import perf_counter
import os

from probabilistic_escape import generate_angles

########################################################################################## UPDATE BELOW BEFORE RUNNING ################################################################################################
# name format: e.g, SC40_probescape_speed3000_chiphunt_0.8cm-datetime
log_dir = r'C:\Users\meisterlab\Desktop\ha_dong_surf2024\data'     # where to save the logs and figures
mouse_id = 'SC44'
escape_strategy = 'classic' # Either 'prob' or 'classic'
chip_length = '0.8' # In cm
trial_num = '1'
speed = 3000    # typically for 3000 the mouse is kinda hard to catch the puck reliably
                # for speeds below 2000 the mouse isn't really engaged. 

if escape_strategy != 'prob' and escape_strategy != 'classic':
    raise ValueError("Invalid escape strategy. Must be 'prob' or 'classic'.")
########################################################################################## UPDATE ABOVE BEFORE RUNNING ################################################################################################

# record experiment details
def get_today_date():
    return datetime.today().strftime('%m%d%Y%H%M%S')
today = str(get_today_date())
experiment_name = f'{mouse_id}_{escape_strategy}escape_speed{speed}_chiphunt_{chip_length}cm'
output_dir = os.path.join(log_dir, f"{experiment_name}-{today}")

print(f"""
Running the experiment... 
Strategy: {escape_strategy}
Speed: {speed}
Mouse ID: {mouse_id}
Chip length: {chip_length}
""")

if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# generate the von Mises distribution for probabilistic escape
if escape_strategy == 'prob':
    print('Generating von Mises distribution...')
    # Define the peaks (mean directions) and their contributions
    peaks = np.array([70, 97, 124, 150, 177, 204])
    contributions = np.array([0.02435718372, 0.08129644245, 0.1926799386, 0.2982947723, 0.3543299546, 0.04904170837])
    kappa = 90  # Concentration parameter
    num_points = 10000

    # Run the function and get the angle array in radians
    angle_array = generate_angles(output_dir, peaks, contributions, kappa, num_points)
    print('von Mises distribution generated.')

class State(Enum):  # state machine. The puck will be in one of these states at any given time
    MIDDLE = 0  # corresponds to the normal case
    LEAVE_CORNER = 1    # will switch to this state when puck is at the corner, exit at constant velocity
                        # will switch back to MIDDLE when puck is some distance away from the corner

def receive_data(ser):
    '''
    ser: serial.Serial object
    A helper function to receive data from the serial port
    '''
    data = ser.read(1024)
    if len(data) == 0:  # no data received
        return None

    data = str(data).replace('b\'', '').replace('\'', '')

    if not (data.startswith('s') and data.endswith('e') and data.count(',') == 3):  # data not formatted properly, just omit this batch
        return None

    data = data.replace('e', '').replace('s', '')   # e and s marks the start and end of the data
    return data

# system parameters
control_gantry = True   # set to False when debugging, system still runs except gantry doesn't move
corr_vec = np.array([483 / 320, 454 / 240]) # convert pixels to milimeter
edges = [(276, 218), (37, 218), (37, 25), (276, 25)] # [(279, 220), (41, 223), (37, 23), (276, 25)]
x_max, x_min, y_max, y_min = 260, 55, 200, 40 #270, 45, 210, 30   
sub_corner_distance = 30        # units in mm, the distance for the system to identify that the puck has left the corner
gantry_history_length = 3       # number of frames to look back for gantry input
trigger_distance = 120          # distance between puck and mouse for the system to start moving the gantry

chip_kf = KalmanFilter( # define the kalman filter for the puck
    np.array([[100], [100]]), # x and y position
    np.eye(2) * 1000,       # initial variance of the state
    np.array([[1., 0.],     # state transition matrix
              [0., 1.]]), 
    np.array([[1., 0.],     # control matrix
              [0., 1.]]),
    np.array([[1., 0.],     # observation matrix
              [0., 1.]]), 
    np.eye(2) * 1,       # observation noise
    np.eye(2) * 5.0         # process noise
    )
# for the kalman filter, the real values to tune are the observation noise and the process noise,
# each of which determines the uncertainty in the camera measurement or the gantry command, 
# the real thing that matters is the ratio between the two and not the absolute values. 

# initialize gantry
utils.print_ports()
ser = serial.Serial('COM6', baudrate=115200, timeout=0.01)
if control_gantry:
    gt = Gantry(port='COM7')

# system state variables
state = State.MIDDLE
escape_vector = np.array([0, 0])    # for storing escape vector, used when puck is trying to leave a corner
vec_gantry = np.zeros((2))          # the vector that is sent to the gantry
gantry_cmd_history = np.zeros((gantry_history_length, 2))   # where the gantry history is stored
prev_mouse_pos = np.zeros((2))  # if camera fails to detect mouse position, previous mouse position is used

# below just for storing parts of the data
mouse_pos_store = []
chip_pos_store = []
chip_pos_raw_store = []
gantry_cmd_store = []

i = 0   # counter, for logging
try:
    while True:
        # try to receive data, continue if no data
        data = receive_data(ser)

        if data is None:
            continue
        tic = perf_counter()
        print(f'i: {i}')
        print(datetime.now())

        #STEP 1: PARSE DATA ON MOUSE AND POSITION FROM SERIAL PORT

        # parsing data into integer pixel values
        mouse_x, mouse_y, chip_x, chip_y = data.split(',')

        # convert to int
        chip_x, chip_y, mouse_x, mouse_y = int(chip_x), int(chip_y), int(mouse_x), int(mouse_y)

        print(f'mouse_px: {mouse_x}, {mouse_y} | chip_px: {chip_x}, {chip_y}')

        # convert to mm
        mouse_pos_mm = np.array([mouse_x, mouse_y]) * corr_vec
        chip_raw_pos_mm = np.array([chip_x, chip_y]) * corr_vec

        print(f'mouse_raw: {mouse_pos_mm[0]}, {mouse_pos_mm[1]} | chip_raw: {chip_raw_pos_mm[0]}, {chip_raw_pos_mm[1]}')

        # STEP 2: PREDICT PUCK POSITION 

        # update kalman filter
        u = gantry_cmd_history[i % gantry_history_length].reshape(2, 1) * 5 # using gantry input from 3 frames ago
        chip_kf.predict(u = u)    # this will correspond to gantry input from 3 frames ago
        if chip_x != -1:
            chip_kf.update(chip_raw_pos_mm.reshape(2, 1))
            
        if mouse_x == -1:
            mouse_pos_mm = prev_mouse_pos
        
        prev_mouse_pos = mouse_pos_mm
        print(f'chip_est: {chip_kf.x[0, 0]}, {chip_kf.x[1, 0]}')


        chip_pos_mm = np.array([chip_kf.x[0, 0], chip_kf.x[1, 0]])

        predicted_chip_pos = chip_pos_mm + np.sum(gantry_cmd_history, axis=0) * 5   # predict the future chip position, *5 is the conversion factor from gantry command to mm
        print(f'predicted_chip_pos: {predicted_chip_pos[0]}, {predicted_chip_pos[1]}')
        chip_x, chip_y = predicted_chip_pos[0] / corr_vec[0], predicted_chip_pos[1] / corr_vec[1]   # convert back to pixel coordinates

        classic_vec = predicted_chip_pos - mouse_pos_mm    # compute the escape vector first, before using the predicted future chip position
        # an interesting biology question, should the prey's escape strategy depend on it's current position or the predator's predicted future position?
        dist = np.linalg.norm(classic_vec)  # distance between puck and mouse
        
        print(f'dist: {dist}')
        print(f'classic_vec: {classic_vec}')
        print(f'state: {state}')

        # STEP 3: ESCAPE STRATEGY 
        if escape_strategy == 'prob':
            op_vec = -classic_vec  # vector pointing from puck to mouse

            # import angle array:
            angle = np.random.choice(angle_array)
            escape_angle = angle if np.random.rand() > 0.5 else -angle
            cos_angle = np.cos(escape_angle)
            sin_angle = np.sin(escape_angle)


            # Define a rotation matrix to rotate 'op_vec' by 'escape_angle'
            rotation_matrix = np.array([
                [cos_angle, -sin_angle],
                [sin_angle, cos_angle]
            ])

            # Generate the escape vector that makes an angle of "escape_angle" with "op_vec"
            prob_vec = rotation_matrix @ op_vec
            print(f'probabilisitc_vec: {prob_vec}')

            # Use this new escape vector for the following calculations
            vec = prob_vec
        
        elif escape_strategy == 'classic':
            vec = classic_vec

        # STEP 4: ADJUST ESCAPE VECTOR BY CORNER AND EDGE (use the classic escape vector for this)

        if state == State.MIDDLE:
            corner = (chip_x >= x_max or chip_x <= x_min) and (chip_y >= y_max or chip_y <= y_min)  # check if puck is at the corner
            if not corner:
                # edge constraints, removing component of vec that is perpendicular to edge
                if chip_x >= x_max:
                    vec = classic_vec
                    vec[0] = min(0, vec[0])
                elif chip_x <= x_min:
                    vec = classic_vec
                    vec[0] = max(0, vec[0])
                if chip_y >= y_max:
                    vec = classic_vec
                    vec[1] = min(0, vec[1])
                elif chip_y <= y_min:
                    vec = classic_vec
                    vec[1] = max(0, vec[1])
                
                print(f'at edge, vec: {vec}')
            else:
                state = State.LEAVE_CORNER  # switch state
                vec = classic_vec
                print('state switch to LEAVE_CORNER')

                at_x_max = int(chip_x >= x_max) * 2 - 1 # 1 if chip_x >= x_max, -1 otherwise
                at_y_max = int(chip_y >= y_max) * 2 - 1 # 1 if chip_y >= y_max, -1 otherwise

                tangent = np.array([at_x_max, -at_y_max])   # tangent vector to the corner
                print(f'tangent: {tangent}')

                # vectors corresponding to the escaping edge
                x_edge = np.array([-at_x_max, 0]) * 10
                y_edge = np.array([0, -at_y_max]) * 10

                # project onto tangent
                tangent_proj = np.dot(vec, tangent)

                if tangent_proj >= 0:
                    escape_vector = y_edge
                else:
                    escape_vector = x_edge

                vec = escape_vector

        elif state == State.LEAVE_CORNER:   # in this state, the puck just moves in the same direction until it leaves corner
            sub_corner = (chip_x >= x_max - sub_corner_distance) and (chip_y >= y_max - sub_corner_distance) \
                        or (chip_x <= x_min + sub_corner_distance) and (chip_y >= y_max - sub_corner_distance) \
                        or (chip_x <= x_min + sub_corner_distance) and (chip_y <= y_min + sub_corner_distance) \
                        or (chip_x >= x_max - sub_corner_distance) and (chip_y <= y_min + sub_corner_distance)
        
            vec = escape_vector

            if not sub_corner:  # when the puck already left the corner
                state = State.MIDDLE
                print('state switch to MIDDLE')
        
        vec = vec / (np.linalg.norm(vec) + 0.01)    # normalize the vector to ensure constant speed #HA# CHECK THIS ??

        print(f'elapsed calculation time: {(perf_counter() - tic) * 1000} ms')

        # STEP 5: ACTUATE GANTRY 
        if control_gantry and dist < trigger_distance:
            vec_gantry = vec * speed / 1000 / 1.3   # require a 1.3 correction factor because otherwise the gantry can't move that far in the given time
            gt.send(f'G01 X{-vec_gantry[0]:.2f} Y{-vec_gantry[1]:.2f} F{speed}', wait_for_read=False)  # Note that the coordinate system of the gantry with respect to the camera is flipped
        else:
            vec_gantry = np.zeros((2))
        
        gantry_cmd_history[i % gantry_history_length] = vec_gantry  # store the gantry command in the history

        # record all variables
        mouse_pos_store.append(mouse_pos_mm)
        chip_pos_store.append(chip_pos_mm)
        gantry_cmd_store.append(vec_gantry)
        chip_pos_raw_store.append(chip_raw_pos_mm)

        i += 1
        print(f'elapsed time: {(perf_counter() - tic) * 1000} ms')
except KeyboardInterrupt:   # save data when interrupted
    print('interrupted')
    ser.close()
    gt.close()

    # plot

    mouse_pos_store = np.array(mouse_pos_store)
    chip_pos_store = np.array(chip_pos_store)
    chip_pos_raw_store = np.array(chip_pos_raw_store)
    gantry_cmd_store = np.array(gantry_cmd_store)
    gantry_position = np.cumsum(gantry_cmd_store, axis=0) * 5 + chip_pos_store[0]

    with open(os.path.join(output_dir, 'mouse_pos_store.pkl'), 'wb+') as f:
        pickle.dump(mouse_pos_store, f)
    with open(os.path.join(output_dir, 'chip_pos_store.pkl'), 'wb+') as f:
        pickle.dump(chip_pos_store, f)
    with open(os.path.join(output_dir, 'chip_pos_raw_store.pkl'), 'wb+') as f:
        pickle.dump(chip_pos_raw_store, f)
    with open(os.path.join(output_dir, 'gantry_cmd_store.pkl'), 'wb+') as f:
        pickle.dump(gantry_cmd_store, f)
    with open(os.path.join(output_dir, 'gantry_position.pkl'), 'wb+') as f:
        pickle.dump(gantry_position, f)


    plt.plot(chip_pos_store[:, 0], label='chip x est')
    plt.plot(chip_pos_raw_store[:, 0], label='chip x raw')
    plt.legend()
    plt.savefig(os.path.join(output_dir, 'chip x.png'))
    plt.close()

    plt.plot(chip_pos_store[:, 1], label='chip y est')
    plt.plot(chip_pos_raw_store[:, 1], label='chip y raw')
    plt.legend()
    plt.savefig(os.path.join(output_dir, 'chip y.png'))
    plt.close()

    plt.plot(chip_pos_store[:, 0], chip_pos_store[:, 1], label='chip est')
    plt.plot(chip_pos_raw_store[:, 0], chip_pos_raw_store[:, 1], label='chip raw')
    plt.plot(gantry_position[:, 0], gantry_position[:, 1], label='gantry pos')
    plt.scatter(chip_pos_store[0, 0], chip_pos_store[0, 1], color='red', s=100, zorder=5, label='start point') #HA# added start point
    plt.xlim(0, 483)
    plt.ylim(0, 454)
    plt.legend()
    plt.gca().invert_xaxis()
    plt.savefig(os.path.join(output_dir, 'chip pos.png'))
    plt.close()

    plt.plot(mouse_pos_store[:, 0], mouse_pos_store[:, 1], label='mouse pos')
    plt.scatter(mouse_pos_store[0, 0], mouse_pos_store[0, 1], color='red', s=100, zorder=5, label='start point') #HA# added start point
    plt.legend()
    plt.xlim(0, 483)
    plt.ylim(0, 454)
    plt.gca().invert_xaxis()
    plt.savefig(os.path.join(output_dir, 'mouse pos.png'))
    plt.close()

    print(f'Experiment on {today} with {escape_strategy} escape of speed {speed} on mouse {mouse_id} completed. Data saved into {log_dir}')