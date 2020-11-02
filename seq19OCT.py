import os
from pathlib import Path
import math

import pandas, multiprocessing, argparse, logging, matplotlib, copy, imageio
matplotlib.use('agg')
import matplotlib.pyplot as plt
from pathlib import Path
from pylab import figure, axes, pie, title, show
import binascii
import codecs 
import json
import zarr, abc, sys, logging
from numcodecs import Blosc
import TensorState.States


# Set the log level to hide some basic warning/info generated by Tensorflow
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# Fix for cudnn error on RTX gpus
os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'

import tensorflow as tf
import tensorflow.keras as keras
from tensorflow.keras.models import load_model
import TensorState as ts
import numpy as np
# np.set_printoptions(threshold=sys.maxsize)
import time
from TensorState import AbstractStateCapture as asc
from TensorState.Layers import StateCapture, StateCaptureHook
# import TensorState.States as tensorstate
import struct
outputim = Path("/home/ec2-user/aIQ/image")

""" Load MNIST and transform it """
# Load the data
mnist = keras.datasets.mnist
(train_images,train_labels), (test_images,test_labels) = mnist.load_data()

# Normalize the data
train_images = train_images/255
test_images = test_images/255

# Add a channel axis
train_images = train_images[..., tf.newaxis]
test_images = test_images[..., tf.newaxis]

""" Create a LeNet-5 model """
# Set the random seed for reproducibility
tf.random.set_seed(0)

# Set the convolutional layer settings
reg = keras.regularizers.l2(0.0005)
kwargs = {'activation': 'elu',
        'kernel_initializer': 'he_normal',
        'kernel_regularizer': reg,
        'bias_regularizer': reg}

# Build the layers
input_layer = keras.layers.Input(shape=(28,28,1), name='input')

# Unit 1
conv_1 = keras.layers.Conv2D(20, 5, name='conv_1',**kwargs)(input_layer)
norm_1 = keras.layers.BatchNormalization(epsilon=0.00001,momentum=0.9)(conv_1)
maxp_1 = keras.layers.MaxPool2D((2,2), name='maxp_1')(norm_1)

# Unit 2
conv_2 = keras.layers.Conv2D(50, 5, name='conv_2', **kwargs)(maxp_1)
norm_2 = keras.layers.BatchNormalization(epsilon=0.00001,momentum=0.9)(conv_2)
maxp_2 = keras.layers.MaxPool2D((2,2), name='maxp_2')(norm_2)

# Fully Connected
conv_3 = keras.layers.Conv2D(100, 4, name='conv_3', **kwargs)(maxp_2)
norm_3 = keras.layers.BatchNormalization(epsilon=0.00001,momentum=0.9)(conv_3)

# Prediction
flatten = keras.layers.Flatten(name='flatten')(norm_3)
pred = keras.layers.Dense(10,name='pred')(flatten)

# Create the Keras model
model = keras.Model(
                    inputs=input_layer,
                    outputs=pred
                )

print(model.summary())

""" Train the model """
# Compile for training
model.compile(
            optimizer=keras.optimizers.SGD(learning_rate=0.001,momentum=0.9,nesterov=True),
            loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True,name='loss'),
            metrics=['accuracy']
            )

# Stop the model once the validation accuracy stops going down
earlystop_callback = tf.keras.callbacks.EarlyStopping(
                            monitor='val_accuracy',
                            mode='max',
                            patience=5,
                            restore_best_weights=True
                        )

# Train the model
# model.fit(
#         train_images, train_labels, epochs=200,
#         validation_data=(test_images, test_labels),
#         batch_size=200,
#         callbacks=[earlystop_callback],
#         verbose=1
#         )

# tf.keras.models.save_model(model=model,filepath='./seq/model.h5')


""" Evaluate model efficiency """
# Attach StateCapture layers to the model
model_after = tf.keras.models.load_model(str(Path('.').joinpath('seq').joinpath('model.h5')), compile=True)
model_before = tf.keras.models.load_model(str(Path('.').joinpath('seq').joinpath('model.h5')), compile=True)
efficiency_model_after = ts.build_efficiency_model(model=model_after,attach_to=['Conv2D','Dense'],method='after', storage_path='./after/')
efficiency_model_before = ts.build_efficiency_model(model=model_before,attach_to=['Conv2D','Dense'],method='before', storage_path='./before/')
# for layer in efficiency_model.efficiency_layers:
#     print("Layer", layer)
#     print("State Counts:", layer.state_count)

# Collect the states for each layer
print()
print('Running model predictions to capture states...')
start = time.time()
predictions_after = efficiency_model_after.predict(test_images,batch_size=200)
predictions_before = efficiency_model_before.predict(test_images,batch_size=200)
print('Finished in {:.3f}s!'.format(time.time() - start))


alpha_vals = range(0, 10000)

print()
print('Getting the number of states in before each layer...')
layerinfo = []
num_ofstates = [[], []]
layer_names = [[], []]
layer_eff = [[], []]
state_freqs = [[],[]]
state_ids = [[], []]
uniq_states = [[], []]
micro_states = [[], []]
max_entropy = [[], []]
numoflayers = 0
for layer in efficiency_model_before.efficiency_layers:
    entropy_dict = {}
    max_entropy[0].append(asc.max_entropy(layer))
    layer_names[0].append(layer.name)
    num_ofstates[0].append(layer.state_count)
    layer_eff[0].append(100*layer.efficiency())
    state_freqs[0].append(asc.counts(layer))
    state_ids[0].append(asc.state_ids(layer))
    uniq_states[0].append(len(state_freqs[0][-1]))
    micro_states[0].append(state_freqs[0][-1].sum())
    numoflayers = numoflayers+1

print()
print('Getting the number of states in after each layer...')
for layer in efficiency_model_after.efficiency_layers:
    entropy_dict = {}
    max_entropy[-1].append(asc.max_entropy(layer))
    layer_names[-1].append(layer.name)
    num_ofstates[-1].append(layer.state_count)
    layer_eff[1].append(100*layer.efficiency())
    #layer.states will return numpy array with boolean values
    state_freqs[-1].append(asc.counts(layer))
    state_ids[-1].append(asc.state_ids(layer))
    uniq_states[-1].append(len(state_freqs[1][-1]))
    micro_states[1].append(state_freqs[1][-1].sum())

for i in range(numoflayers):
    if i == 0:
        continue
    print("Layer ", i+1)
    print("Layer Names: ",layer_names[0][i], "|", layer_names[1][i])
    print("Number of States: ",num_ofstates[0][i], "|", num_ofstates[1][i])
    print("Layer Efficiency (Percent): ", layer_eff[0][i], "|", layer_eff[1][i])
    print("Number of Unique States: ", uniq_states[0][i], "|", uniq_states[1][i])
    print("Number of Microstates: ", micro_states[0][i], "|", micro_states[1][i])
    print("Max Entropy: ", max_entropy[0][i], "|", max_entropy[1][i]) #number of neurons
    print("")

    print("BEFORE")
    for state in range(0, uniq_states[0][i]):
        bytearr = bytearray(state_ids[0][i][state])
        bytearr = np.array([bytearr])
        decompress = TensorState.States.decompress_states(bytearr, max_entropy[0][i])
        # sort_edge, sort_index = TensorState.States.sort_states(bytearr, int(uniq_states[0][i]))
        print(state_freqs[0][i][state], decompress)
        # print(sort_edge)
        # print(sort_index)
    print("AFTER")
    for state in range(0, uniq_states[1][i]):
        # bytearr = bytearray(np.array([(state_ids[1][i])]))
        bytearr = bytearray(state_ids[1][i][state])
        bytearr = np.array([bytearr])
        # print(bytearr)
        decompress = TensorState.States.decompress_states(bytearr, max_entropy[1][i])
        # sort_edge, sort_index = TensorState.States.sort_states(bytearr, int(uniq_states[1][i]))
        print(state_freqs[1][i][state], decompress)
        # print(sort_edge)
        # print(sort_index)
    
    break

# print("Layer Names: ", layer_names)
# print("Number of States: ", num_ofstates)
# print("Layer Efficiency: ", layer_eff)
# print("Number of Unique States: ", uniq_states)
# print("Number of Microstates: ", micro_states)
    # for alpha in alpha_vals:
    #     entropy_val = asc.entropy(layer, alpha=alpha)
    #     entropy_dict[alpha] = entropy_val
    #     if math.isinf(entropy_val):
    #         break

    # plt.subplot(2,2,i)
    # plt.plot(*zip(*sorted(entropy_dict.items())))
    # plt.title(layer.name)
    # plt.xlabel("Alpha Values")
    # plt.ylabel("Entropy")
    # plt.scatter(0, entropy_dict[0])
    # plt.scatter(1, entropy_dict[1])
    # plt.scatter(2, entropy_dict[2])
    # plt.scatter(alpha-1, entropy_dict[alpha-1])

    # i = i + 1
    # print(" ")

# plt.tight_layout()
# plt.savefig('image.png')

# # Calculate each layers efficiency
# print()
# print('Evaluating efficiency of each layer...')
# for layer in efficiency_model.efficiency_layers:
#     start = time.time()
#     print('Layer {} efficiency: {:.1f}% ({:.3f}s)'.format(layer.name,100*layer.efficiency(),time.time() - start))

# # Calculate the aIQ
# beta = 2 # fudge factor giving a slight bias toward accuracy over efficiency

# print()
# print('Network metrics...')
# print('Beta: {}'.format(beta))

# network_efficiency = ts.network_efficiency(efficiency_model)
# print('Network efficiency: {:.1f}%'.format(100*network_efficiency))

# accuracy = np.sum(np.argmax(predictions,axis=1)==test_labels)/test_labels.size
# print('Network accuracy: {:.1f}%'.format(100*accuracy))

# aIQ  = ts.aIQ(network_efficiency,accuracy,beta)
# print('aIQ: {:.1f}%'.format(100*aIQ))
