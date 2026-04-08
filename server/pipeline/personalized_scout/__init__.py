"""Personalized scout generation pipeline (L2/L3).

A parallel implementation of the generation pipeline that produces
fully-personalized scout text by asking the model for multiple named
blocks in a single structured-output call.

The existing L1 pipeline in `pipeline.orchestrator` is NOT touched —
this module is a fresh build for the extension's developer mode.
"""
