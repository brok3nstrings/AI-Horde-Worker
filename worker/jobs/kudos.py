import pickle
import sys

import torch


class KudosModel:
    """Calculate kudos for a given horde job payload. Tiny, lightweight cpu model.

    Simple usage example:

        # Initial one time setup (filename of the model)
        kudos_model = KudosModel("kudos-v12-10.ckpt")

        # If our job JSON is in "payload":
        kudos = kudos_model.calculate_kudos(payload)

    """

    # "The general idea is for a 50 step 512x512 image to cost 10 Kudos"
    KUDOS_BASIS = 10.0

    # This is the payload we use to describe the job that is worth the KUDOS_BASIS above
    BASIS_PAYLOAD = {
        "width": 512,
        "height": 512,
        "ddim_steps": 50,
        "cfg_scale": 7.5,
        "denoising_strength": 1.0,
        "control_strength": 1.0,
        "karras": True,
        "hires_fix": False,
        "source_image": False,
        "source_mask": False,
        "source_processing": "txt2img",
        "sampler_name": "k_euler",
        "control_type": "None",
        "post_processing": [],
    }

    # Don't change of these constants unless the model has been changed and retained beforehand.
    # Samplers, post processors, etc that are unknown to this code will simply be given somewhat
    # sensible defaults.
    KNOWN_POST_PROCESSORS = [
        "4x_AnimeSharp",
        "CodeFormers",
        "GFPGAN",
        "NMKD_Siax",
        "RealESRGAN_x2plus",
        "RealESRGAN_x4plus_anime_6B",
        "RealESRGAN_x4plus",
        "strip_background",
    ]

    KNOWN_SAMPLERS = [
        "ddim",
        "k_dpm_2_a",
        "k_dpm_2",
        "k_dpm_adaptive",
        "k_dpm_fast",
        "k_dpmpp_2m",
        "k_dpmpp_2s_a",
        "k_dpmpp_sde",
        "k_euler_a",
        "k_euler",
        "k_heun",
        "k_lms",
        "plms",
        "uni_pc_bh2",
        "uni_pc",
    ]

    KNOWN_CONTROL_TYPES = [
        "canny",
        "depth",
        "fakescribbles",
        "hed",
        "hough",
        "None",
        "normal",
        "openpose",
        "scribble",
        "seg",
    ]

    KNOWN_SOURCE_PROCESSING = [
        "img2img",
        "inpainting",
        "outpainting",
        "txt2img",
    ]

    def __init__(self, model_filename=None):
        # Our basis time
        self.time_basis = 0
        # Our model
        self.model = None

        # Avoid any terrible mistakes in one hot encoding
        KudosModel.KNOWN_POST_PROCESSORS.sort()
        KudosModel.KNOWN_SAMPLERS.sort()
        KudosModel.KNOWN_CONTROL_TYPES.sort()
        KudosModel.KNOWN_SOURCE_PROCESSING.sort()

        # Load the model if required
        if model_filename:
            self.load_model(model_filename)

    # Payload to kudos
    def calculate_kudos(self, payload, basis_adjustment=0, basis_scale=1):
        if not self.model:
            raise Exception("No kudos model loaded")

        if not self.time_basis:
            raise Exception("Kudos model failed to calculate basis time.")

        # Get time for this job
        job_time = self.payload_to_time(payload)

        # What is the ratio between our basis time and this job time? i.e. How much longer
        # will this job take than our reference job that's worth 10 kudos?
        job_ratio = job_time / self.time_basis

        # Determine our kudos basis (was 10 originally)
        kudos = KudosModel.KUDOS_BASIS

        # Add any requested fixed value adjustment
        kudos = kudos + basis_adjustment

        # Adjust by any requested scaling
        kudos = kudos * basis_scale

        # Scale our kudos by the time the job will take to complete
        kudos = job_ratio * kudos

        return kudos

    @classmethod
    def one_hot_encode(cls, strings, unique_strings):
        one_hot = torch.zeros(len(strings), len(unique_strings))
        for i, string in enumerate(strings):
            one_hot[i, unique_strings.index(string)] = 1
        return one_hot

    @classmethod
    def one_hot_encode_combined(cls, strings, unique_strings):
        one_hot = torch.zeros(len(strings), len(unique_strings))
        for i, string in enumerate(strings):
            one_hot[i, unique_strings.index(string)] = 1

        return torch.sum(one_hot, dim=0, keepdim=True)

    @classmethod
    def payload_to_tensor(cls, payload):
        data = []
        data_samplers = []
        data_control_types = []
        data_source_processing_types = []
        data_post_processors = []
        data.append(
            [
                payload["height"] / 1024,
                payload["width"] / 1024,
                payload["ddim_steps"] / 100,
                payload["cfg_scale"] / 30,
                payload.get("denoising_strength", 1.0),
                payload.get("control_strength", payload.get("denoising_strength", 1.0)),
                1.0 if payload["karras"] else 0.0,
                1.0 if payload.get("hires_fix", False) else 0.0,
                1.0 if payload.get("source_image", False) else 0.0,
                1.0 if payload.get("source_mask", False) else 0.0,
            ],
        )
        data_samplers.append(
            payload["sampler_name"] if payload["sampler_name"] in KudosModel.KNOWN_SAMPLERS else "k_euler",
        )
        data_control_types.append(payload.get("control_type", "None"))
        data_source_processing_types.append(payload.get("source_processing", "txt2img"))
        data_post_processors = payload.get("post_processing", [])[:]

        _data_floats = torch.tensor(data).float()
        _data_samplers = cls.one_hot_encode(data_samplers, KudosModel.KNOWN_SAMPLERS)
        _data_control_types = cls.one_hot_encode(data_control_types, KudosModel.KNOWN_CONTROL_TYPES)
        _data_source_processing_types = cls.one_hot_encode(
            data_source_processing_types,
            KudosModel.KNOWN_SOURCE_PROCESSING,
        )
        _data_post_processors = cls.one_hot_encode_combined(data_post_processors, KudosModel.KNOWN_POST_PROCESSORS)
        return torch.cat(
            (_data_floats, _data_samplers, _data_control_types, _data_source_processing_types, _data_post_processors),
            dim=1,
        )

    def load_model(self, model_filename):
        with open(model_filename, "rb") as infile:
            self.model = pickle.load(infile)
        self.calculate_basis_time()
        return self.model

    # Pass in a horde payload, get back a predicted time in seconds
    def payload_to_time(self, payload):
        inputs = self.payload_to_tensor(payload).squeeze()
        with torch.no_grad():
            output = self.model(inputs)
        return round(float(output.item()), 2)

    # Determine how long the basic job that costs KUDOS_BASIS kudos takes to run
    def calculate_basis_time(self):
        self.time_basis = self.payload_to_time(self.BASIS_PAYLOAD)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Syntax: kudos.py <model_filename>")

    kudos_model = KudosModel(sys.argv[1])

    print(f"Kudos basis is {kudos_model.KUDOS_BASIS}")
    print(f"Time basis is {kudos_model.time_basis} seconds")

    # Test the basis job
    job_kudos = kudos_model.calculate_kudos(KudosModel.BASIS_PAYLOAD)
    print(f"The basis job worth {job_kudos} kudos, " f"expected {KudosModel.KUDOS_BASIS} kudos")

    # Test fixed kudos basis adjustment
    job_kudos = kudos_model.calculate_kudos(KudosModel.BASIS_PAYLOAD, 5)
    print(f"Adjusting a job by +5 worth {job_kudos}, " f"expected {KudosModel.KUDOS_BASIS+5} kudos")

    # Test fixed kudos basis adjustment and percentage scaling
    job_kudos = kudos_model.calculate_kudos(KudosModel.BASIS_PAYLOAD, 5, 1.25)
    print(f"Adjusting a job by +5 and +25% worth {job_kudos}, " f"expected {(KudosModel.KUDOS_BASIS+5)*1.25} kudos")
