import numpy as np
import copy
from sklearn.metrics._classification import accuracy_score
import sys
from tensorflow import keras
from tensorflow.data import Dataset
import tensorflow as tf
from keras import Model
import argparse
import rebuild_layers as rl
import template_architectures
import random

class CKA():
    __name__ = 'CKA'
    def __init__(self):
        pass

    def _debiased_dot_product_similarity_helper(self, xty, sum_squared_rows_x, sum_squared_rows_y, squared_norm_x, squared_norm_y, n):
        return ( xty - n / (n - 2.) * sum_squared_rows_x.dot(sum_squared_rows_y) + squared_norm_x * squared_norm_y / ((n - 1) * (n - 2)))

    def feature_space_linear_cka(self, features_x, features_y, debiased=False):
        features_x = features_x - np.mean(features_x, 0, keepdims=True)
        features_y = features_y - np.mean(features_y, 0, keepdims=True)

        dot_product_similarity = np.linalg.norm(features_x.T.dot(features_y)) ** 2
        normalization_x = np.linalg.norm(features_x.T.dot(features_x))
        normalization_y = np.linalg.norm(features_y.T.dot(features_y))

        if debiased:
            n = features_x.shape[0]
            # Equivalent to np.sum(features_x ** 2, 1) but avoids an intermediate array.
            sum_squared_rows_x = np.einsum('ij,ij->i', features_x, features_x)
            sum_squared_rows_y = np.einsum('ij,ij->i', features_y, features_y)
            squared_norm_x = np.sum(sum_squared_rows_x)
            squared_norm_y = np.sum(sum_squared_rows_y)

            dot_product_similarity = self._debiased_dot_product_similarity_helper(
                dot_product_similarity, sum_squared_rows_x, sum_squared_rows_y,
                squared_norm_x, squared_norm_y, n)
            normalization_x = np.sqrt(self._debiased_dot_product_similarity_helper(
                normalization_x ** 2, sum_squared_rows_x, sum_squared_rows_x,
                squared_norm_x, squared_norm_x, n))
            normalization_y = np.sqrt(self._debiased_dot_product_similarity_helper(
                normalization_y ** 2, sum_squared_rows_y, sum_squared_rows_y,
                squared_norm_y, squared_norm_y, n))

        return dot_product_similarity / (normalization_x * normalization_y)

    def scores(self,  model, X_train=None, y_train=None, allowed_layers=[]):
        output = []

        F = Model(model.input, model.get_layer(index=-2).output)
        features_F = F.predict(X_train, verbose=0)

        F_line = Model(model.input, model.get_layer(index=-2).output)
        for layer_idx in allowed_layers:
            _layer = F_line.get_layer(index=layer_idx - 1)
            _w = _layer.get_weights()
            _w_original = copy.deepcopy(_w)

            for i in range(0, len(_w)):
                _w[i] = np.zeros(_w[i].shape)

            _layer.set_weights(_w)
            features_line = F_line.predict(X_train, verbose=0)

            _layer.set_weights(_w_original)

            score = self.feature_space_linear_cka(features_F, features_line)
            output.append((layer_idx, 1 - score))

        return output

def load_model(architecture_file='', weights_file=''):
    import tensorflow.keras as keras
    from keras.utils.generic_utils import CustomObjectScope
    from keras import backend as K
    from tensorflow.keras import layers

    def _hard_swish(x):
        return x * K.relu(x + 3.0, max_value=6.0) / 6.0

    def _relu6(x):
        return K.relu(x, max_value=6)

    if '.json' not in architecture_file:
        architecture_file = architecture_file+'.json'

    with open(architecture_file, 'r') as f:
        with CustomObjectScope({'relu6': _relu6,
                                'DepthwiseConv2D': layers.DepthwiseConv2D,
                                '_hard_swish': _hard_swish}):
            model = keras.models.model_from_json(f.read())

    if weights_file != '':
        if '.h5' not in weights_file:
            weights_file = weights_file + '.h5'
        model.load_weights(weights_file)
        print('Load architecture [{}]. Load weights [{}]'.format(architecture_file, weights_file), flush=True)
    else:
        print('Load architecture [{}]'.format(architecture_file), flush=True)

    return model

def compute_flops(model):
    #useful link https://www.programmersought.com/article/27982165768/
    import keras
    #from keras.applications.mobilenet import DepthwiseConv2D
    from tensorflow.keras.layers import DepthwiseConv2D
    total_flops =0
    flops_per_layer = []

    for layer_idx in range(1, len(model.layers)):
        layer = model.get_layer(index=layer_idx)
        if isinstance(layer, DepthwiseConv2D) is True:
            _, output_map_H, output_map_W, current_layer_depth = layer.output_shape

            _, _, _, previous_layer_depth = layer.input_shape
            kernel_H, kernel_W = layer.kernel_size

            #Computed according to https://arxiv.org/pdf/1704.04861.pdf Eq.(5)
            flops = (kernel_H * kernel_W * previous_layer_depth * output_map_H * output_map_W) + (previous_layer_depth * current_layer_depth * output_map_W * output_map_H)
            total_flops += flops
            flops_per_layer.append(flops)

        elif isinstance(layer, keras.layers.Conv2D) is True:
            _, output_map_H, output_map_W, current_layer_depth = layer.output_shape

            _, _, _, previous_layer_depth = layer.input_shape
            kernel_H, kernel_W = layer.kernel_size

            flops = output_map_H * output_map_W * previous_layer_depth * current_layer_depth * kernel_H * kernel_W
            total_flops += flops
            flops_per_layer.append(flops)

        if isinstance(layer, keras.layers.Dense) is True:
            _, current_layer_depth = layer.output_shape

            _, previous_layer_depth = layer.input_shape

            flops = current_layer_depth * previous_layer_depth
            total_flops += flops
            flops_per_layer.append(flops)

    return total_flops, flops_per_layer

def statistics(model, i):
    flops, _ = compute_flops(model)
    blocks = rl.count_blocks(model)

    print('Iteration [{}] Blocks {} FLOPS [{}]'.format(i, blocks, flops), flush=True)


def finetuning(model, X_train, y_train):
    sgd = keras.optimizers.SGD(learning_rate=0.01, decay=1e-6, momentum=0.9, nesterov=True)
    model.compile(loss='categorical_crossentropy', optimizer=sgd, metrics=['accuracy'])

    model.fit(X_train, y_train, batch_size=128, verbose=0, epochs=10)

    return model

if __name__ == '__main__':
    np.random.seed(2)

    rl.architecture_name = 'ResNet56'
    debug = True

    (X_train, y_train), (X_test, y_test) = keras.datasets.cifar10.load_data()

    X_train = X_train.astype('float32') / 255
    X_test = X_test.astype('float32') / 255

    X_train_mean = np.mean(X_train, axis=0)
    X_train -= X_train_mean
    X_test -= X_train_mean

    if debug:
        n_samples = 10
        n_classes = len(np.unique(y_train, axis=0))
        n_samples = n_samples * n_classes
        y_ = np.argmax(y_train, axis=1)
        sub_sampling = [np.random.choice(np.where(y_ == value)[0], n_samples, replace=False) for value in np.unique(y_)]
        sub_sampling = np.array(sub_sampling).reshape(-1)

        X_train = X_train[sub_sampling]
        y_train = y_train[sub_sampling]

    y_train = tf.keras.utils.to_categorical(y_train, 10)
    y_test = tf.keras.utils.to_categorical(y_test, 10)

    model = load_model('ResNet56')
    model = finetuning(model, X_train, y_train)

    statistics(model, 'Unpruned')

    for i in range(10):

        allowed_layers = rl.blocks_to_prune(model)
        layer_method = CKA()
        scores = layer_method.scores(model, X_train, y_train, allowed_layers)
        model = finetuning(model, X_train, y_train)
        model = rl.rebuild_network(model, scores, p_layer=1)
        statistics(model, i)