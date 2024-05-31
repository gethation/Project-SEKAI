import cv2
import mediapipe as mp
import numpy as np
import os
from moviepy.video.io.VideoFileClip import VideoFileClip
import json

mp_hands = mp.solutions.hands
hands = mp_hands.Hands(max_num_hands=2)  # 设置最大追踪手的数量
mp_drawing = mp.solutions.drawing_utils

def detect(frame, keypoint_coordinates, show):
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    results = hands.process(rgb_frame)

    if results.multi_hand_landmarks:
        landmark_coords = [[0,0] for _ in range(42)]
        for (landmarks, handedness) in zip(results.multi_hand_landmarks, results.multi_handedness):
            if show:
                mp_drawing.draw_landmarks(
                    frame, landmarks, mp_hands.HAND_CONNECTIONS)

            replacement = []
            for i, landmark in enumerate(landmarks.landmark):
                landmark_x = int(landmark.x * frame.shape[1])
                landmark_y = int(landmark.y * frame.shape[0])
                replacement.append([landmark_x, landmark_y])
            if handedness.classification[0].index == 1: #index 1 = Right
                landmark_coords[:21] = replacement
            else:
                landmark_coords[21:] = replacement
        keypoint_coordinates.append(landmark_coords)
    return frame

def procedure(video_path, crop, show = False):
    cap = cv2.VideoCapture(video_path)

    keypoint_coordinates = []

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        frame = pre_adjust(frame, crop)
        detect(frame, keypoint_coordinates, show)

        if show:
            cv2.imshow('Hand Tracking', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    if show:
        cap.release()
        cv2.destroyAllWindows()
    
    return keypoint_coordinates

def fixed(keypoint_coordinates):
    keypoint_coordinates = np.array(keypoint_coordinates)
    f = 0
    l_index = -1
    r_index = -1
    print(keypoint_coordinates.shape)
    for i in range(keypoint_coordinates[:,f].shape[0]-1):
        left = keypoint_coordinates[i,f]
        right = keypoint_coordinates[i+1,f]
        if sum(left) != 0 and sum(right) == 0:
            l_index = i+1
        if sum(left) == 0 and sum(right) != 0:
            r_index = i+1
        if l_index < r_index:
            keypoint_coordinates[l_index-1:r_index+1,0:20] = np.linspace(keypoint_coordinates[l_index-1,0:20],
                                                                        keypoint_coordinates[r_index,0:20],
                                                                        keypoint_coordinates[l_index-1:r_index+1,f].shape[0])
    f = 21
    l_index = -1
    r_index = -1
    for i in range(keypoint_coordinates[:,f].shape[0]-1):
        left = keypoint_coordinates[i,f]
        right = keypoint_coordinates[i+1,f]
        if sum(left) != 0 and sum(right) == 0:
            l_index = i+1
        if sum(left) == 0 and sum(right) != 0:
            r_index = i+1
        if l_index < r_index:
            keypoint_coordinates[l_index-1:r_index+1,21:] = np.linspace(keypoint_coordinates[l_index-1,21:],
                                                                        keypoint_coordinates[r_index,21:],
                                                                        keypoint_coordinates[l_index-1:r_index+1,f].shape[0])
    return keypoint_coordinates

def elongate(keypoint_coordinates_dim, new_length):

    new_indices = np.linspace(0, len(keypoint_coordinates_dim) - 1, new_length)
    new_array = np.interp(new_indices, np.arange(len(keypoint_coordinates_dim)), keypoint_coordinates_dim)

    return new_array

def extend(keypoint_coordinates, new_length):
    filled_keypoint_coordinates = np.zeros((new_length, 42, 2))
    for i in range(keypoint_coordinates.shape[1]-1):
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
        frame = frame[360:750, 1460:1810]
        # frame = frame[0:1080, 0:1920]
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

def format_srt(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as file:
        content = file.readlines()

    formatted_content = []
    for line in content:
        formatted_content.append(line.strip() + '\n')

    with open(output_file, 'w', encoding='utf-8') as file:
        file.writelines(formatted_content)

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
    scale_factor = np.random.uniform(0.7, 1.6)
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
connections = [i for i in x]+[ (i[0]+21, i[1]+21) for i in x]

def visualize(input_file):
    with open(input_file, 'r') as f:
        coordinates = json.load(f)
    coordinates = np.array(coordinates)
    # coordinates = takeout_zero(coordinates)
    coordinates = random_rotate(coordinates)
    coordinates = random_scaling(coordinates)
    coordinates = offsetalize(coordinates)
    keypoint_coordinates = extend(coordinates, 300).astype(np.int16)
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
            if i >= 21:
                color = (0, 0, 255)
            else:
                color = (255, 0, 0)
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