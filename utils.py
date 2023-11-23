import contextlib
import torch
import torch.nn as nn
import cv2
from ultralytics.nn.modules import (AIFI, C1, C2, C3, C3TR, SPP, SPPF, Bottleneck, BottleneckCSP, C2f, C3Ghost, C3x,
                                    Classify, Concat, Conv, Conv2, ConvTranspose, Detect, DWConv, DWConvTranspose2d,
                                    Focus, GhostBottleneck, GhostConv, HGBlock, HGStem, Pose, RepC3,
                                    RTDETRDecoder, Segment)
from ultralytics.utils import LOGGER, colorstr
from ultralytics.utils.torch_utils import (make_divisible)
import numpy as np
from PIL import Image
import pandas as pd
import sys
from ultralytics.models.yolo.detect import DetectionPredictor


BASE_LABEL_FILE_PATH = "/share/projects/cicero/objdet/dataset/CICERO_stereo/train_label/1_Varengeville_sur_Mer/"


def image_to_label_path(img_file,patch1=True):

    img_file = img_file.split("/")
    patch_name = "patches_cm1_txt" if patch1 else "patches_cm2_txt"

    # tiles_201802171130571_13440_09920.png -> tiles_201802171130571_13440_09920.txt
    img_file[-1] = img_file[-1].replace('.png', '.txt')

    label_path = BASE_LABEL_FILE_PATH + img_file[9] +  "/patches_cm_indiv_stereo/" + patch_name + "/" + img_file[-1]

    return label_path



def get_label_info(path,index):

    bboxes = []
    batch_idx = []
    cls = []

    with open(path, 'r') as file:
            # Read lines from the file
        lines = file.readlines()

        for line in lines:
            data = line.strip().split(',')
            #cls.append(float(data[0])) # class
            cls.append(0) # class
            bboxes.append(np.array([float(data[1]),float(data[2]),float(data[3]),float(data[4])] ))
            batch_idx.append(index)

        bboxes = np.array(bboxes)
        cls = np.array(cls)
        batch_idx = np.array(batch_idx)


    return {"bboxes":bboxes,"cls":cls,"batch_idx":batch_idx}

def load_image(file_path):
    try:
        #return np.array(Image.open(file_path))
        return np.array(cv2.imread(file_path, cv2.IMREAD_UNCHANGED))
    except:
        print("Error couldn't open the file : ",file_path)



def get_min_max_dataset(mode="train"):
    # get the min and max of a dataset
    df = pd.read_csv(f"csv/image_{mode}_split.csv")
    le_max = -1
    le_min = sys.maxsize

    for i in range(len(df)):
        row = df.iloc[i]
        patch1 = row["patch1"]
        patch2 = row["patch2"]

        file = patch1
        image = cv2.imread(file, cv2.IMREAD_UNCHANGED)
        image = image[:,:,:3]
        max_1 = np.max(image)
        min_1 = np.min(image)
        if pd.isna(patch2):
            le_max = max(le_max,max_1)
            le_min = min(min_1,le_min)

        else:
            file2 = patch2
            image_2 = cv2.imread(file2, cv2.IMREAD_UNCHANGED)
            image_2 = image_2[:,:,:3]
            max_2 = np.max(image_2)
            min_2 = np.min(image_2)

            le_max = max(max_1,max_2,le_max)
            le_min = min(min_1,min_2,le_min)

    return le_max,le_min



def pred_one_image(model,image_path,mode="train",output_file=None):

    if output_file == None:
       output_file = "pred_res.txt"

    predictor = DetectionPredictor()

    image = load_image(image_path)
    image = image[:,:,:3]
    image_max = np.max(image)
    image_min = np.min(image)
    image = ((image - image_min) / (image_max - image_min))

    image = torch.tensor(image).float().permute(2, 0, 1)
    image = image.unsqueeze(0)

    x = predictor(source=image ,model=model)
    x[0].save_txt(output_file,True)


def save_image_using_label(image_path,label_path,save_path):
    """
    method used for quick check & test
    goal: save an image after drawing the bounding box
    using his label file, which mean we do not make any prediction
    """

    image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    image = image[:,:,:3]
    image_max = np.max(image)
    image_min = np.min(image)
    image = ((image - image_min) / (image_max - image_min)) * 255

    label = get_label_info(label_path,index=0) # index is not important here
    label_bboxes = label["bboxes"]

    height, width, _ = image.shape

    for box in label_bboxes:
        x, y, w, h = [int(v * width) for v in box]  # Convert relative coordinates to pixels
        x1, y1 = x - w // 2, y - h // 2  # Calculate top-left corner
        x2, y2 = x + w // 2, y + h // 2  # Calculate bottom-right corner
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)  # Draw rectangle

    cv2.imwrite(save_path, image)









## YOLOV8 METHOD
def parse_my_detection_model(d, ch, verbose=True):  # model_dict, input_channels(3)
    """Parse a YOLO model.yaml dictionary into a PyTorch model."""
    """
    Code imported
    file: ultralytics/nn/task.py
    Just the line for i, (f, n, m, args) in enumerate(d['backbone'] + d['head])
    has been changed to  for i, (f, n, m, args) in enumerate(d['backbone'] + d['head1'] + d['head2'] )
    """
    import ast

    # Args
    max_channels = float('inf')
    nc, act, scales = (d.get(x) for x in ('nc', 'activation', 'scales'))
    depth, width, kpt_shape = (d.get(x, 1.0) for x in ('depth_multiple', 'width_multiple', 'kpt_shape'))
    if scales:
        scale = d.get('scale')
        if not scale:
            scale = tuple(scales.keys())[0]
            LOGGER.warning(f"WARNING ⚠️ no model scale passed. Assuming scale='{scale}'.")
        depth, width, max_channels = scales[scale]

    if act:
        Conv.default_act = eval(act)  # redefine default activation, i.e. Conv.default_act = nn.SiLU()
        if verbose:
            LOGGER.info(f"{colorstr('activation:')} {act}")  # print

    if verbose:
        LOGGER.info(f"\n{'':>3}{'from':>20}{'n':>3}{'params':>10}  {'module':<45}{'arguments':<30}")
    ch = [ch]
    layers, save, c2 = [], [], ch[-1]  # layers, savelist, ch out



    for i, (f, n, m, args) in enumerate((d['backbone'] + d['head1']) + d['head2']):  # from, number, module, args
        m = getattr(torch.nn, m[3:]) if 'nn.' in m else globals()[m]  # get module
        for j, a in enumerate(args):
            if isinstance(a, str):
                with contextlib.suppress(ValueError):
                    args[j] = locals()[a] if a in locals() else ast.literal_eval(a)

        n = n_ = max(round(n * depth), 1) if n > 1 else n  # depth gain
        if m in (Classify, Conv, ConvTranspose, GhostConv, Bottleneck, GhostBottleneck, SPP, SPPF, DWConv, Focus,
                 BottleneckCSP, C1, C2, C2f, C3, C3TR, C3Ghost, nn.ConvTranspose2d, DWConvTranspose2d, C3x, RepC3):
            c1, c2 = ch[f], args[0]
            if c2 != nc:  # if c2 not equal to number of classes (i.e. for Classify() output)
                c2 = make_divisible(min(c2, max_channels) * width, 8)

            args = [c1, c2, *args[1:]]
            if m in (BottleneckCSP, C1, C2, C2f, C3, C3TR, C3Ghost, C3x, RepC3):
                args.insert(2, n)  # number of repeats
                n = 1
        elif m is AIFI:
            args = [ch[f], *args]
        elif m in (HGStem, HGBlock):
            c1, cm, c2 = ch[f], args[0], args[1]
            args = [c1, cm, c2, *args[2:]]
            if m is HGBlock:
                args.insert(4, n)  # number of repeats
                n = 1

        elif m is nn.BatchNorm2d:
            args = [ch[f]]
        elif m is Concat:
            c2 = sum(ch[x] for x in f)
        elif m in (Detect, Segment, Pose):
            args.append([ch[x] for x in f])
            if m is Segment:
                args[2] = make_divisible(min(args[2], max_channels) * width, 8)
        elif m is RTDETRDecoder:  # special case, channels arg must be passed in index 1
            args.insert(1, [ch[x] for x in f])
        else:
            c2 = ch[f]

        m_ = nn.Sequential(*(m(*args) for _ in range(n))) if n > 1 else m(*args)  # module
        t = str(m)[8:-2].replace('__main__.', '')  # module type
        m.np = sum(x.numel() for x in m_.parameters())  # number params
        m_.i, m_.f, m_.type = i, f, t  # attach index, 'from' index, type
        if verbose:
            LOGGER.info(f'{i:>3}{str(f):>20}{n_:>3}{m.np:10.0f}  {t:<45}{str(args):<30}')  # print
        save.extend(x % i for x in ([f] if isinstance(f, int) else f) if x != -1)  # append to savelist
        layers.append(m_)
        if i == 0:
            ch = []
        ch.append(c2)


    return nn.Sequential(*layers), sorted(save)
