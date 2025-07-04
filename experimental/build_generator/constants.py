#!/usr/bin/env python3
# Copyright 2024 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Holds constants used for from-scratch generation."""

SHARED_MEMORY_RESULTS_DIR = "autogen-results"
PROJECT_BASE = "temp-project-"

MODEL_GPT_35_TURBO = "gpt-3.5-turbo"
MODEL_GPT_4 = "gpt-4"
MODEL_VERTEX = "vertex"
MODELS = [MODEL_GPT_35_TURBO, MODEL_VERTEX]

MAX_PROMPT_LENGTH = 25000

INTROSPECTOR_OSS_FUZZ_DIR = "/src/inspector"
INTROSPECTOR_ALL_FUNCTIONS_FILE = "all-fuzz-introspector-functions.json"

# Common -l<lib> to required package mapping for Dockerfile installation
LIBRARY_PACKAGE_MAP = {
    "z": "zlib1g-dev",
    "bz2": "libbz2-dev",
    "ssl": "libssl-dev",
    "crypto": "libssl-dev",
    "c++": "libc++-dev",
    "c++abi": "libc++abi-dev",
    "gtest": "libgtest-dev",
    "gmock": "libgmock-dev",
    "brotlidec": "libbrotli-dev",
    "brotlienc": "libbrotli-dev",
    "divsufsort": "libdivsufsort-dev",
    "divsufsort64": "libdivsufsort-dev",
}
