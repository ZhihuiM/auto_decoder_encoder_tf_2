""" train and test for a convolutional neural network for predicting face attrubute for celebA """

import os
import time
import glob
import numpy as np
import pandas as pd
import PIL
import tensorflow as tf
import tensorflow.keras
import tensorflow.keras.applications
import tensorflow.keras.layers as layers
from tensorflow.keras.applications.mobilenet import preprocess_input
print("Num GPUs Available: ", len(tf.config.experimental.list_physical_devices('GPU')))
import math

from absl import app, flags, logging
from absl.flags import FLAGS
import cv2
import os
import numpy as np
import tensorflow as tf

from modules.evaluations import get_val_data, perform_val
from modules.models import ArcFaceModel
from modules.utils import set_memory_growth, load_yaml, l2_norm
# early stoppping
from tensorflow.keras.callbacks import EarlyStopping


path_celeba_img = '../../data/CelebA/img_align_celeba'  # './data/processed/celebA_crop'
path_celeba_att = '../../data/CelebA/list_attr_celeba.txt'  #'./data/raw/celebA_annotation/list_attr_celeba.txt'
path_model_save = 'checkpoints/cnn_face_attr_celeba'

""" create path if not exist """
for path_used in [path_celeba_img, path_celeba_att, path_model_save]:
    if not os.path.exists(path_used):
        os.mkdir(path_used)


def create_cnn_model(size_output=None, tf_print=False):
    """
    create keras model with convolution layers of MobileNet and added fully connected layers on to top
    :param size_output: number of nodes in the output layer
    :param tf_print:    True/False to print
    :return: keras model object
    """

    if size_output is None:
        # get number of attrubutes, needed for defining the final layer size of network
        df_attr = pd.read_csv(path_celeba_att, sep='\s+', header=1, index_col=0)
        size_output = df_attr.shape[1]

    cfg = load_yaml('configs/arc_res50.yaml')

    base_model = ArcFaceModel(size=cfg['input_size'],
                         backbone_type=cfg['backbone_type'],
                         training=False)

    # Load the convolutional layers of pretrained model: mobilenet
    # base_model = tensorflow.keras.applications.mobilenet.MobileNet(include_top=False, input_shape=(128,128,3),
    #                                                       alpha=1, depth_multiplier=1,
    #                                                       dropout=0.001, weights="imagenet",
    #                                                       input_tensor=None, pooling=None)

    # add fully connected layers
    fc0 = base_model.output
    # fc0_pool = layers.GlobalAveragePooling2D(data_format='channels_last', name='fc0_pool')(fc0)
    fc1 = layers.Dense(256, activation='relu', name='fc1_dense')(fc0)
    # fc2 = layers.Dense(128, activation='relu', name='fc2_dense')(fc1)
    fc3 = layers.Dense(size_output, activation='tanh', name='fc3_dense')(fc1)

    model = tensorflow.keras.models.Model(inputs=base_model.input, outputs=fc3)

    # freeze the early layers
    for layer in base_model.layers:
        layer.trainable = False

    sgd = tensorflow.keras.optimizers.SGD(learning_rate=0.0001)

    model.compile(optimizer=sgd, loss='mean_squared_error')

    if tf_print:
        print('use convolution layers of MobileNet, add fully connected layers')
        print(model.summary())

    return model


def get_data_info(path_celeba_img=path_celeba_img, path_celeba_att=path_celeba_att, yn_print_head_tail=False):
    """
    function to get names of images files and and pandas data-frame containing face attributes

    :param path_celeba_img: path to image files directory (cropped to 128*128)
    :param path_celeba_att: path to face attribute file (the original txt)
    :param yn_print_head_tail: true/false to print head and tail of data
    :return: img_names(list of file names of images), df_attr (pandas dataframe of face attributes)
    """
    df_attr = pd.read_csv(path_celeba_att, sep='\s+', header=1, index_col=0)

    img_names = os.listdir(path_celeba_img)
    img_names = [img_name for img_name in img_names if img_name[-4:]=='.jpg']
    img_names.sort()

    assert df_attr.shape[0] == len(img_names), 'images number does not match attribute table'

    if yn_print_head_tail:
        print(df_attr.head(3))
        print(df_attr.tail(3))
        print(img_names[:3])
        print(img_names[-3:])

    assert df_attr.shape[0] == len(img_names), \
        'images number does not match attribute table'
    assert set(img_names) == set(df_attr.index.tolist()), \
        'image names are not consistent between image files and attribute table '

    return img_names, df_attr


try:
    img_names, df_attr = get_data_info()
    num_image, num_attr = df_attr.shape
except:
    raise Exception('can not reach data needed for training, here we can only do test')


def get_data_sample(img_idx=None, img_name=None, yn_interactive_plot=False):
    """
    function to load one image and the corresponding attributes, either using idx_img or img_name

    :param img_idx:    index of image
    :param img_name:   name of image, will overwrite img_idx if given
    :param yn_interactive_plot: True/False to print the sample
    :return:           image (3d array, H*W*RGB), attributes (1d array)
    """

    if img_name is None:  # if not given, use img_idx to find the name
        if img_idx is None:  # if not given, randomly select one
            img_idx = np.random.randint(num_image)
        img_name = img_names[img_idx]
    size = (112, 112)# add by the xingbo
    img = np.asarray(PIL.Image.open(os.path.join(path_celeba_img, img_name)).resize(size))  # load image
    labels = df_attr.loc[img_name]                                             # get labels

    if yn_interactive_plot:  # if show things interactively for verification
        import matplotlib.pyplot as plt
        print(labels)
        print("image file name: {}".format(img_name) )
        plt.imshow(img)
        plt.show()

    x = img
    y = np.array(labels)
    return x, y


def load_data_batch(num_images_total=None):
    """
    load data and preprocess before feeding it to Keras model
    :param num_images_total:
    :return:
    """

    list_x, list_y = [], []

    if num_images_total is None:
        image_names_select = img_names
    else:
        image_names_select = np.random.choice(img_names, num_images_total, replace=False)


    for img_name in image_names_select:
        x, y = get_data_sample(img_name=img_name, yn_interactive_plot=False)
        list_x.append(x)
        list_y.append(y)

    x_batch = np.stack(list_x, axis=0)
    y_batch = np.stack(list_y, axis=0)

    x_batch_ready = preprocess_input(x_batch.copy())
    y_batch_ready = np.array(y_batch, dtype='float32')

    return x_batch_ready, y_batch_ready

##
def train_protocol():
    """ train the model with model.fit() """

    model = create_cnn_model(tf_print=True)

    # tensorflow.keras.optimizers.Adagrad(lr=0.01, epsilon=1e-08, decay=0.0)
    # tensorflow.keras.optimizers.Adadelta(lr=1.0, rho=0.95, epsilon=1e-08, decay=0.0)
    # tensorflow.keras.optimizers.RMSprop(lr=0.001, rho=0.9, epsilon=1e-08, decay=0.0)
    optimizer = tensorflow.keras.optimizers.Adam(lr=0.001, beta_1=0.9, beta_2=0.999, epsilon=1e-08, decay=0.0)

    # initial_learning_rate = 0.05
    # def lr_exp_decay(epoch, lr):
    #     k = 0.1
    #     return initial_learning_rate * math.exp(-k * epoch)
    #
    # sgd = tensorflow.keras.optimizers.SGD(learning_rate=0.0001)

    model.compile(optimizer=optimizer, loss='mean_squared_error')
    # model.compile(optimizer='adam', loss='mean_squared_error')
    x_all, y_all = load_data_batch(num_images_total=2**16)#16

    early_stopping = EarlyStopping(monitor='val_loss', patience=3, verbose=2)
    # scheduler_callback = tensorflow.keras.callbacks.LearningRateScheduler(lr_exp_decay, verbose=1)

    model.fit(x=x_all, y=y_all, batch_size=128, epochs=50, verbose=1,
              validation_split=0.125, shuffle=True,callbacks=[early_stopping])

    name_model_save = os.path.join(path_model_save, 'model_{}.h5'.format(gen_time_str()))
    model.save(filepath=name_model_save)

    return model


##
def gen_time_str():
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime())

def get_list_model_save(path_model_save=path_model_save):
    return glob.glob(os.path.join(path_model_save, 'model*.h5'))
