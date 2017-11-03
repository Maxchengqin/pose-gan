import numpy as np

import matplotlib
matplotlib.use('Agg')

from gan.dataset import UGANDataset
import pose_utils
import pose_transform

from skimage.io import imread
import pandas as pd
import os

class PoseHMDataset(UGANDataset):
    def __init__(self, images_dir, batch_size, image_size, pairs_file, annotations_file,
                 use_input_pose, warp_skip, disc_type, tmp_pose_dir, shuffle=True):
        super(PoseHMDataset, self).__init__(batch_size, None)
        self._batch_size = batch_size
        self._image_size = image_size
        self._images_dir = images_dir
        self._pairs_file = pd.read_csv(pairs_file)
        self._annotations_file = pd.read_csv(annotations_file, sep=':')
        self._annotations_file = self._annotations_file.set_index('name')
        self._use_input_pose = use_input_pose
        self._warp_skip = warp_skip
        self._shuffle = shuffle
        self._disc_type = disc_type
        self._tmp_pose = tmp_pose_dir
        if not os.path.exists(self._tmp_pose):
            os.makedirs(self._tmp_pose) 
        print ("Number of images: %s" % len(self._annotations_file))
        print ("Number of pairs: %s" % len(self._pairs_file))

        self._batches_before_shuffle = int(self._annotations_file.shape[0] // self._batch_size)

    def number_of_batches_per_epoch(self):
        return 1000#self._annotations_file.shape[0] // self._batch_size
       

    def compute_pose_map_batch(self, pair_df, direction):
        assert direction in ['to', 'from']
        batch = np.empty([self._batch_size] + list(self._image_size) + [18])
        i = 0
        for _, p in pair_df.iterrows():
            row = self._annotations_file.loc[p[direction]]
            file_name = self._tmp_pose + p[direction] + '.npy'
            if os.path.exists(file_name):
                pose = np.load(file_name)
            else:
                kp_array = pose_utils.load_pose_cords_from_strings(row['keypoints_y'], row['keypoints_x'])
                pose = pose_utils.cords_to_map(kp_array, self._image_size)
                np.save(file_name, pose)
            batch[i] = pose
            i += 1
        return batch

    def compute_cord_warp_batch(self, pair_df):
        batch = [np.empty([self._batch_size] + [10, 8])]
        if self._warp_skip == 'mask':
            batch.append(np.empty([self._batch_size, 10] + list(self._image_size)))
        i = 0
        for _, p in pair_df.iterrows():
            fr = self._annotations_file.loc[p['from']]
            to = self._annotations_file.loc[p['to']]
            kp_array1 = pose_utils.load_pose_cords_from_strings(fr['keypoints_y'],
                                                                fr['keypoints_x'])
            kp_array2 = pose_utils.load_pose_cords_from_strings(to['keypoints_y'],
                                                                to['keypoints_x'])

            batch[0][i] = pose_transform.affine_transforms(kp_array1, kp_array2)
            if self._warp_skip == 'mask':
                batch[1][i] = pose_transform.pose_masks(kp_array2, self._image_size)
            i += 1
        return batch

    def _preprocess_image(self, image):
        return (image / 255 - 0.5) * 2

    def _deprocess_image(self, image):
        return (255 * (image + 1) / 2).astype('uint8')

    def load_image_batch(self, pair_df, direction='from'):
        assert direction in ['to', 'from']
        batch = np.empty([self._batch_size] + list(self._image_size) + [3])
        i = 0
        for _, p in pair_df.iterrows():
            batch[i] = imread(os.path.join(self._images_dir, p[direction]))
            i += 1
        return self._preprocess_image(batch)

    def load_batch(self, index, for_discriminator):
        pair_df = self._pairs_file.iloc[index]
        result = [self.load_image_batch(pair_df, 'from')]
        if self._use_input_pose:
            result.append(self.compute_pose_map_batch(pair_df, 'from'))
        result.append(self.load_image_batch(pair_df, 'to'))
        result.append(self.compute_pose_map_batch(pair_df, 'to'))

        if self._warp_skip != 'none' and (not for_discriminator or self._disc_type == 'warp'):
            result += self.compute_cord_warp_batch(pair_df)
        return result

    def next_generator_sample(self):
        index = self._next_data_index()
        return self.load_batch(index, False)

    def next_discriminator_sample(self):
        index = self._next_data_index()
        return self.load_batch(index, True)

    def _shuffle_data(self):
        if self._shuffle:
            self._pairs_file = self._pairs_file.sample(frac=1)
        
    def display(self, output_batch, input_batch):
        row = self._batch_size
        col = 1

        tg_app = self._deprocess_image(input_batch[0])
        tg_pose = input_batch[3 if self._use_input_pose else 2]
        tg_img = input_batch[2 if self._use_input_pose else 1]
        tg_img = self._deprocess_image(tg_img)

        res_img = self._deprocess_image(output_batch[2 if self._use_input_pose else 1])

        tg_app = super(PoseHMDataset, self).display(tg_app, None, row=row, col=col)

        pose_images = np.array([pose_utils.draw_pose_from_map(pose)[0] for pose in tg_pose])
        tg_pose = super(PoseHMDataset, self).display(pose_images, None, row=row, col=col)

        tg_img = super(PoseHMDataset, self).display(tg_img, None, row=row, col=col)
        res_img = super(PoseHMDataset, self).display(res_img, None, row=row, col=col)

        return np.concatenate(np.array([tg_app, tg_pose, tg_img, res_img]), axis=1)
