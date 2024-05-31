import cv2
import mediapipe as mp
import numpy as np
import os
from moviepy.video.io.VideoFileClip import VideoFileClip
import json
import time
import torch
from torch import nn
import torchvision
import torchvision.transforms as transforms

# 初始化mediapipe手部和姿態模型
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(max_num_hands=2)
mp_pose = mp.solutions.pose
pose = mp_pose.Pose()
mp_drawing = mp.solutions.drawing_utils

def detect(frame, keypoint_coordinates, pose_coordinates, show):
    # 確保frame是一個有效的影像
    if frame is None:
        raise ValueError("Invalid frame input")

    # 轉換影像從BGR到RGB
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # 處理影像，找出手部關節點
    hand_results = hands.process(rgb_frame)
    landmark_coords = [[0, 0] for _ in range(42)]
    if hand_results.multi_hand_landmarks:
        for landmarks, handedness in zip(hand_results.multi_hand_landmarks, hand_results.multi_handedness):
            if show:
                # 繪製手部關節點和連接線
                mp_drawing.draw_landmarks(frame, landmarks, mp_hands.HAND_CONNECTIONS)

            replacement = []
            for i, landmark in enumerate(landmarks.landmark):
                landmark_x = int(landmark.x * frame.shape[1])
                landmark_y = int(landmark.y * frame.shape[0])
                replacement.append([landmark_x, landmark_y])
            # 根據左右手分配座標
            if handedness.classification[0].index == 1:  # index 1 = Right
                landmark_coords[:21] = replacement
            else:
                landmark_coords[21:] = replacement

    # 更新手部關節點座標列表
    keypoint_coordinates.append(landmark_coords)

    # 處理影像，找出姿態關節點
    pose_results = pose.process(rgb_frame)
    selected_indices = [i for i in range(25)]  # 自定義需要的點
    filtered_pose_landmarks = [[0, 0] for _ in range(25)]
    replacement = []
    if pose_results.pose_landmarks:
        for i in selected_indices:
            landmark = pose_results.pose_landmarks.landmark[i]
            pose_x = int(landmark.x * frame.shape[1])
            pose_y = int(landmark.y * frame.shape[0])
            replacement.append([pose_x, pose_y])
        if show:
            # 繪製過濾後的姿態關節點
            for landmark in replacement:
                cv2.circle(frame, tuple(landmark), 5, (255, 0, 0), -1)
        filtered_pose_landmarks[:25] = replacement
    # 更新姿態關節點座標列表
    pose_coordinates.append(filtered_pose_landmarks)

    # return frame

def procedure(video_path, crop, show = False):
    cap = cv2.VideoCapture(video_path)

    hand_coordinates = []
    pose_coordinates = []
    i = 0
    while cap.isOpened():
        ret, frame = cap.read()
        i+=1
        if not ret:
            break
        frame = pre_adjust(frame, crop)
        detect(frame, hand_coordinates, pose_coordinates, show)

        if show:
            cv2.imshow('Hand Tracking', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    if show:
        cap.release()
        cv2.destroyAllWindows()
    
    return {'hand':hand_coordinates,'pose':pose_coordinates}, i


def fixed(keypoint_coordinates):
    keypoint_coordinates = np.array(keypoint_coordinates)
    total_points = keypoint_coordinates.shape[1]
    num_pose_points = total_points - 42  # Automatically calculate the number of pose points
    print(keypoint_coordinates.shape)

    def interpolate_missing_points(coords, start_index, end_index):
        """Interpolate missing points between start_index and end_index."""
        # 确保start_index和end_index形成一个有效的范围
        if start_index >= 0 and end_index >= 0 and start_index < end_index and (end_index + 1 <= len(coords)):
            coords[start_index-1:end_index+1] = np.linspace(
                coords[start_index-1], 
                coords[end_index], 
                end_index - start_index + 2
            )
        return coords

    def fix_coords(coords, offset, num_points):
        """Fix coordinates for the specified offset and number of points."""
        l_index = -1
        r_index = -1
        n = len(coords)
        for i in range(n - 1):
            left = coords[i, offset]
            right = coords[i + 1, offset]
            if sum(left) != 0 and sum(right) == 0:
                l_index = i + 1
            if sum(left) == 0 and sum(right) != 0 and l_index != -1:
                r_index = i + 1
                coords[:, offset:offset+num_points] = interpolate_missing_points(coords[:, offset:offset+num_points], l_index, r_index)
                l_index = -1  # 重置l_index以等待下一个有效段的开始
        return coords

    keypoint_coordinates = fix_coords(keypoint_coordinates, 0, 21)   # Fix left hand (21 points)
    keypoint_coordinates = fix_coords(keypoint_coordinates, 21, 21)  # Fix right hand (21 points)
    keypoint_coordinates = fix_coords(keypoint_coordinates, 42, num_pose_points)  # Fix pose coordinates

    return keypoint_coordinates

def elongate(keypoint_coordinates_dim, new_length):

    new_indices = np.linspace(0, len(keypoint_coordinates_dim) - 1, new_length)
    new_array = np.interp(new_indices, np.arange(len(keypoint_coordinates_dim)), keypoint_coordinates_dim)

    return new_array

def extend(keypoint_coordinates, new_length):
    filled_keypoint_coordinates = np.zeros((new_length, keypoint_coordinates.shape[1], 2))
    for i in range(keypoint_coordinates.shape[1]):
        filled_keypoint_coordinates[:, i, 0] = elongate(keypoint_coordinates[:, i, 0], new_length)
        filled_keypoint_coordinates[:, i, 1] = elongate(keypoint_coordinates[:, i, 1], new_length)

    return filled_keypoint_coordinates

def takeout_zero(keypoint_coordinates):
    zero_cols = np.all(keypoint_coordinates == 0, axis=(1,2))

    # 刪除全為零的列
    arr_without_zero_cols = keypoint_coordinates[~zero_cols, :, :]
    return arr_without_zero_cols

def pre_adjust(frame, crop):
    if crop:
        # frame = frame[360:750, 1460:1810]
        height, width, _ = frame.shape
        box_size = 400  
        x = (width - box_size) // 2
        y = (height - box_size) // 2
        frame = frame[y:y+box_size, x:x + box_size]
    if frame.shape[1] >= frame.shape[0]:
        l = frame.shape[1]//2-frame.shape[0]//2
        r = frame.shape[1]//2+frame.shape[0]//2
        frame = frame[:,l:r,:]
    if frame.shape[1] <= frame.shape[0]:
        t = frame.shape[0]//2-frame.shape[1]//2
        b = frame.shape[0]//2+frame.shape[1]//2
        frame = frame[t:b,:,:]
    frame = cv2.resize(frame, (640, 640))

    return frame

def split_video(video_path, output_folder, start_time, limit_time):
    video_clip = VideoFileClip(video_path)
    base_filename = os.path.splitext(os.path.basename(video_path))[0]

    segment_clip = video_clip.subclip(start_time, limit_time)
    segment_filename = os.path.join(output_folder, f"{base_filename}_segment_{0}.mp4")
    segment_clip.write_videofile(segment_filename)

    video_clip.reader.close()

def time_to_seconds(time_str):
    time_parts = time_str.replace(',', ':').split(':')
    h = int(time_parts[0])
    m = int(time_parts[1])
    s = int(time_parts[2])
    ms = int(time_parts[3])
    
    return h * 3600 + m * 60 + s + ms / 1000

def parse_srt(filename):
    subtitles = []

    with open(filename, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    subtitle = None
    for line in lines:
        line = line.strip()
        if line.isdigit():
            if subtitle is not None:
                subtitles.append(subtitle)
            subtitle = {'index': int(line)}
        elif '-->' in line:
            start_end = line.split('-->')
            start_time, end_time = [time.strip() for time in start_end]
            if subtitle is not None:
                subtitle['start_time'] = start_time
                subtitle['end_time'] = end_time
                subtitle['start_seconds'] = time_to_seconds(start_time)
                subtitle['end_seconds'] = time_to_seconds(end_time)
        elif line and subtitle is not None:
            if 'text' in subtitle:
                subtitle['text'] += ' ' + line
            else:
                subtitle['text'] = line

    if subtitle is not None:
        subtitles.append(subtitle)

    return subtitles

def rotate_point(point, center, angle):

    offset = point - center

    # 创建旋转矩阵
    rotation_matrix = np.array([[np.cos(angle), -np.sin(angle)],
                                [np.sin(angle), np.cos(angle)]])

    # 使用旋转矩阵旋转偏移量
    rotated_offset = np.dot(rotation_matrix, offset)

    # 将旋转后的偏移量添加回圆心坐标以获取旋转后的点
    rotated_point = rotated_offset + center

    return rotated_point

def scaling_point(point, center, scale_factor):

    # 计算点相对于圆心的偏移量
    offset = point - center

    # 使用缩放因子对偏移量进行缩放
    scaled_offset = offset * scale_factor

    # 将缩放后的偏移量添加回圆心坐标以获取缩放后的点
    scaled_point = scaled_offset + center

    return scaled_point

def random_rotate(coordinates):
    angle = np.radians(np.random.randint(-20, 20))
    center = [320, 320]
    rotated_coordinates = np.empty_like(coordinates)
    for i, frame in enumerate(coordinates):
        for j, point in enumerate(frame):
            rotated_coordinates[i,j] = rotate_point(point, center, angle)
    return rotated_coordinates

def random_scaling(coordinates):
    scale_factor = np.random.uniform(0.6, 1.5)
    center = [320, 320]
    scaled_coordinates = np.empty_like(coordinates)
    for i, frame in enumerate(coordinates):
        for j, point in enumerate(frame):
            scaled_coordinates[i,j] = scaling_point(point, center, scale_factor)
    return scaled_coordinates

def offsetalize(coordinates):
    offset = np.random.randint(-30, 30, 2)
    offsetalized_coordinates = np.empty_like(coordinates)
    for i, frame in enumerate(coordinates):
        for j, point in enumerate(frame):
            offsetalized_coordinates[i,j] = point + offset
    return offsetalized_coordinates

x = [(i, i+1) for i in range(0,4)]+[(i, i+1) for i in range(5,8)]+[(i, i+1) for i in range(9,12)]+[(i, i+1) for i in range(13,16)]+[(i, i+1) for i in range(17,19)]+[(0,5),(0,17),(5,9),(9,13),(13,17)]
connections = [i for i in x]+[ (i[0]+21, i[1]+21) for i in x] + [(i[0]+42, i[1]+42) for i in [(12,11),(12,14),(11,13),(13,0-42),(14,21-42)]]


def visualize(input_file, lenth=64):
    with open(input_file, 'r') as f:
        coordinates = json.load(f)
    coordinates = np.array(coordinates)
    # coordinates = takeout_zero(coordinates)
    # coordinates = random_rotate(coordinates)
    # coordinates = random_scaling(coordinates)
    # coordinates = offsetalize(coordinates)
    keypoint_coordinates = extend(coordinates, lenth).astype(np.int16)
    print(coordinates.shape, keypoint_coordinates.shape)
    # 创建黑色背景
    background = 255 * np.ones((640, 640, 3), dtype=np.uint8)

    # 指定要连接的点的索引

    for keypoints in keypoint_coordinates:
        # 创建黑色背景的副本
        frame = background.copy()

        # 绘制关键点
        for i, keypoint in enumerate(keypoints):
            x, y = keypoint[0], keypoint[1]
            if i <= 20:
                color = (255, 0, 0)
            elif i > 20 and i <= 42:
                color = (0, 0, 255)
            else: color = (0, 0, 0)
                
            if i == 41 or i == 20:
                pass
            else:
                cv2.circle(frame, (x, y), 5, color, -1)

        # 连接指定的点
        for connection in connections:
            start_point = tuple(keypoints[connection[0]])
            end_point = tuple(keypoints[connection[1]])
            cv2.line(frame, start_point, end_point, (0, 255, 0), 2)

        cv2.imshow('Hand Key Points', frame)

        if cv2.waitKey(100) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()

def put_text(frame, elapsed_time, break_time, recording_time, num=0):

    cv2.putText(frame, f'Time: {float(elapsed_time):.1f} seconds', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
    # cv2.putText(frame, f'NuM: {num}/{100}', (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)

    # 计算方框的位置
    height, width, _ = frame.shape
    box_size = 360
    x = (width - box_size) // 2
    y = (height - box_size) // 2

    # 绘制方框
    cv2.rectangle(frame, (x, y), (x + box_size, y + box_size), (255, 0, 0), 1)
    
    if elapsed_time <= break_time:
        cv2.rectangle(frame, (0, height-15), (int((elapsed_time/break_time)*width), height), (0, 0, 250), -1)
    if elapsed_time > break_time:
        cv2.rectangle(frame, (0, height-15), (int(((elapsed_time-break_time)/recording_time)*width), height), (0, 250, 0), -1)

    return frame

def web_cam(break_time=3, recording_time = 2, save_folder = ''):
    segment = []
    cap = cv2.VideoCapture(0)

    # 检查摄像头是否成功打开
    if not cap.isOpened():
        print("无法打开摄像头")
        exit()

    # 定义视频编码器并创建VideoWriter对象
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # 使用MP4编码器
    out = cv2.VideoWriter(os.path.join(save_folder, 'output.mp4'), fourcc, 30.0, (640, 480))  # 参数分别为输出文件名，编码器，帧率和分辨率


    # 初始化实时帧率计算器
    frame_counter = 0
    start_frame = 0
    end_frame = 0
    num = 0
    start_time = time.time()

    while True:
        ret, frame = cap.read()  # 读取一帧图像
        # frame = cv2.resize(frame, (1280, 960))
        if not ret:
            print("无法获取图像")
            break
        # 将当前帧写入输出视频文件
        out.write(frame)
        frame_counter += 1
        elapsed_time = time.time() - start_time


        # 计算经过的时间
        frame = put_text(frame, elapsed_time, break_time, recording_time, num)


        if elapsed_time < break_time:
            start_frame = frame_counter

        if elapsed_time >= break_time + recording_time:
            start_time = time.time()

            end_frame = frame_counter
            segment.append((start_frame, end_frame))
            break

        # 在窗口中显示当前帧
        frame = cv2.resize(frame, (1280, 960))
        cv2.imshow('', frame)
        # 按下 'q' 键退出循环
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break


    # 释放所有资源
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    with open(os.path.join(save_folder,'time mark.json'), 'w') as file:
        json.dump(segment, file)

def web_cam_photo(break_time=2, save_folder = '', img_path=None):
    segment = []
    cap = cv2.VideoCapture(0)

    # 检查摄像头是否成功打开
    if not cap.isOpened():
        print("无法打开摄像头")
        exit()

    # 定义视频编码器并创建VideoWriter对象
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # 使用MP4编码器
    out = cv2.VideoWriter(os.path.join(save_folder, 'output.mp4'), fourcc, 30.0, (640, 480))  # 参数分别为输出文件名，编码器，帧率和分辨率


    # 初始化实时帧率计算器
    frame_counter = 0
    start_frame = 0
    end_frame = 0
    num = 0
    start_time = time.time()

    while True:
        ret, frame = cap.read()  # 读取一帧图像
        # frame = cv2.resize(frame, (1280, 960))
        if not ret:
            print("无法获取图像")
            break
        # 将当前帧写入输出视频文件
        if img_path == None:
            out.write(frame)
        else:
            x = cv2.imread(img_path)
            # dsize = (640,852)
            # x = cv2.resize(x, dsize)
            # x = x[0:640,0:640]
            out.write(x)
        frame_counter += 1
        elapsed_time = time.time() - start_time


        # 计算经过的时间
        frame = put_text(frame, elapsed_time, break_time, num)


        if elapsed_time < break_time:
            start_frame = frame_counter

        if start_frame+1 == frame_counter:
            start_time = time.time()

            end_frame = frame_counter
            segment.append((start_frame, end_frame))
            break

        # 在窗口中显示当前帧
        frame = cv2.resize(frame, (1280, 960))
        cv2.imshow('', frame)
        # 按下 'q' 键退出循环
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break


    # 释放所有资源
    cap.release()
    out.release()
    cv2.destroyAllWindows()
    with open(os.path.join(save_folder,'time mark.json'), 'w') as file:
        json.dump(segment, file)

def node_json(input_video, output_folder):

    keypoint_coordinates, i = procedure(input_video, crop=True, show=True)
    print(len(keypoint_coordinates), i)
    output_file = os.path.join(output_folder, 'nodes.json')
    x = np.concatenate((np.array(keypoint_coordinates['hand']),
                    np.array(keypoint_coordinates['pose'])), 1)
    with open(output_file, 'w') as f:
        json.dump(x.tolist(), f, indent=4)

def split_json(input_json, output_folder, time_mark_path, uniform_length):

    os.makedirs(output_folder, exist_ok=True)

    with open(input_json, 'r') as f:
        coordinates_jason = json.load(f)
    with open(time_mark_path, 'r') as f:
        time_mark = json.load(f)
    
    for (pointerL, pointerR) in time_mark:
        keypoint_coordinates = coordinates_jason[pointerL: pointerR]
        keypoint_coordinates = fixed(keypoint_coordinates)
        keypoint_coordinates = takeout_zero(keypoint_coordinates)
        keypoint_coordinates = extend(keypoint_coordinates, uniform_length).tolist()

        output_file = os.path.join(output_folder, f'segment_{0}'+'.json')

        with open(output_file, 'w') as f:
            json.dump(keypoint_coordinates, f, indent=4)
        pass

def coordinate_transform(coordinate):
    coordinate = np.array(coordinate)
    container = np.empty((64, 40, 2))
    container[:, :20, :] = coordinate[:, :20, :]
    container[:, 20:, :] = coordinate[:, 21:41, :]
    return container

def normalize_data(tensor, mean, std):
    # mean = tensor.mean()
    # std = tensor.std()
    normalize = transforms.Normalize(mean=[mean], std=[std])
    normalized_tensor = normalize(tensor)
    return normalized_tensor

def augmentation(x):
    # coordinates = np.array(x)
    # if np.random.rand()>0.5:
    #     coordinates = flip(coordinates)
    coordinates = random_rotate(x)
    coordinates = random_scaling(x)
    keypoint_coordinates = offsetalize(coordinates)
    return keypoint_coordinates

def load_json(path, mean, std, augment = False):
    with open(path, 'r') as file:
        json_ = json.load(file)
    x = coordinate_transform(json_)
    if augment:
        x = augmentation(x)
    data = torch.as_tensor(torch.from_numpy(x), dtype=torch.float32)
    batch = normalize_data(data, mean, std)

    return batch.unsqueeze(0)