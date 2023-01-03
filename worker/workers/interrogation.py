"""This is the worker, it's the main workhorse that deals with getting requests, and spawning data processing"""
import time
import traceback

import requests

from nataili.util import logger
from worker.jobs.stable_diffusion import InterrogationHordeJob
from worker.stats import bridge_stats
from worker.workers.framework import WorkerFramework

class InterrogationWorker(WorkerFramework):

    # Setting it as it's own function so that it can be overriden
    def can_process_jobs(self):
        # can_do = len(self.model_manager.get_loaded_models_names()) > 0
        can_do = True
        if not can_do:
            logger.info(
                "No models loaded. Waiting for the first model to be up before polling the horde"
            )
        return can_do


    def pop_job(self):
        return super().pop_job(InterrogationHordeJob)


    def reload_data(self):
        """This is just a utility function to reload the configuration"""
        super().reload_data()
        self.bridge_data.check_models(self.model_manager)
        self.bridge_data.reload_models(self.model_manager)
