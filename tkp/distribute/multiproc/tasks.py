"""
Parallisable tasks used with python multiprocessing
"""
from __future__ import absolute_import
import logging
import tkp.steps


logger = logging.getLogger(__name__)


def save_to_mongodb(zipped):
    logger.info("running persistence task")
    images, args = zipped
    [image_cache_config] = args
    return tkp.steps.persistence.save_to_mongodb(images, image_cache_config)


def extract_metadatas(zipped):
    logger.info("running extract metadatas task")
    images, args = zipped
    sigma, f = args
    return tkp.steps.persistence.extract_metadatas(images, sigma, f)


def quality_reject_check(zipped):
    logger.info("running quality task")
    url, args = zipped
    job_config = args[0]
    return tkp.steps.quality.reject_check(url, job_config)


def extract_sources(zipped):
    logger.info("running extracted sources task")
    accessor, args = zipped
    extraction_params = args[0]
    return tkp.steps.source_extraction.extract_sources(accessor,
                                                       extraction_params)


def get_accessors(zipped):
    logger.debug("Creating accessors for images")
    images, args = zipped
    return tkp.steps.persistence.get_accessors(images)


def get_start_time(zipped):
    logger.debug("Retrieving start time from accessors")
    images, args = zipped
    return [a.taustart_ts for a in tkp.steps.persistence.get_accessors(images)]
