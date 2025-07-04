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
"""
Tools used for experiments.
"""
import atexit
import logging
import os
import re
import shutil
import subprocess as sp
import tempfile
import uuid

import yaml

from experiment import benchmark as benchmarklib

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

BUILD_DIR: str = "build"
GLOBAL_TEMP_DIR: str = ""
ENABLE_CACHING = bool(int(os.getenv("OFG_USE_CACHING", "1")))
# Assume OSS-Fuzz is at repo root dir by default.
# This will change if temp_dir is used.
OSS_FUZZ_DIR: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "oss-fuzz"
)
CLEAN_UP_OSS_FUZZ = bool(int(os.getenv("OFG_CLEAN_UP_OSS_FUZZ", "1")))

VENV_DIR: str = "venv"


def _remove_temp_oss_fuzz_repo():
    """Deletes the temporary OSS-Fuzz directory."""
    # Ensure we aren't deleting a real repo someone cares about.
    assert not OSS_FUZZ_DIR.endswith("oss-fuzz")
    try:
        shutil.rmtree(OSS_FUZZ_DIR)
    except PermissionError as e:
        logger.warning("No permission to remove %s: %s", OSS_FUZZ_DIR, e)
    except FileNotFoundError as e:
        logger.warning("No OSS-Fuzz directory %s: %s", OSS_FUZZ_DIR, e)


def _set_temp_oss_fuzz_repo():
    """Creates a temporary directory for OSS-Fuzz repo and update |OSS_FUZZ_DIR|."""
    # Holding the temp directory in a global object to ensure it won't be deleted
    # before program ends.
    global GLOBAL_TEMP_DIR
    GLOBAL_TEMP_DIR = tempfile.mkdtemp()
    global OSS_FUZZ_DIR
    OSS_FUZZ_DIR = GLOBAL_TEMP_DIR
    atexit.register(_remove_temp_oss_fuzz_repo)
    _clone_oss_fuzz_repo()


def _clone_oss_fuzz_repo():
    """Clones OSS-Fuzz to |OSS_FUZZ_DIR|."""
    clone_command = [
        "git",
        "clone",
        "https://github.com/google/oss-fuzz",
        "--depth",
        "1",
        OSS_FUZZ_DIR,
    ]
    proc = sp.Popen(clone_command, stdout=sp.PIPE, stderr=sp.PIPE, stdin=sp.DEVNULL)
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        logger.info(stdout)
        logger.info(stderr)


def clone_oss_fuzz(oss_fuzz_dir: str = ""):
    """Clones the OSS-Fuzz repository."""
    if oss_fuzz_dir:
        global OSS_FUZZ_DIR
        OSS_FUZZ_DIR = oss_fuzz_dir
    else:
        _set_temp_oss_fuzz_repo()

    if not os.path.exists(OSS_FUZZ_DIR):
        _clone_oss_fuzz_repo()

    if CLEAN_UP_OSS_FUZZ:
        clean_command = ["git", "clean", "-fxd", "-e", VENV_DIR, "-e", BUILD_DIR]
        sp.run(
            clean_command,
            capture_output=True,
            stdin=sp.DEVNULL,
            check=True,
            cwd=OSS_FUZZ_DIR,
        )

    # Sync oss-fuzz data if needed.
    if os.environ.get("OSS_FUZZ_DATA_DIR", ""):
        src_projects = os.path.join(os.environ["OSS_FUZZ_DATA_DIR"], "projects")
        logger.info("OSS_FUZZ_DATA_DIR: %s", os.environ["OSS_FUZZ_DATA_DIR"])
        logger.info("src_projects: %s", src_projects)
        for proj in os.listdir(src_projects):
            src_project = os.path.join(src_projects, proj)
            dst_project = os.path.join(OSS_FUZZ_DIR, "projects", proj)
            logger.info("Copying: %s to %s", src_project, dst_project)
            shutil.copytree(src_project, dst_project)


def postprocess_oss_fuzz() -> None:
    """Prepares the oss-fuzz directory for experiments."""
    # Write .gcloudignore to make submitting to GCB faster.
    with open(os.path.join(OSS_FUZZ_DIR, ".gcloudignore"), "w") as f:
        f.write("__pycache__\n")
        f.write("build\n")
        f.write(".git\n")
        f.write(".pytest_cache\n")
        f.write("venv\n")

    # Set up dependencies to run OSS-Fuzz build scripts
    if os.path.exists(os.path.join(OSS_FUZZ_DIR, VENV_DIR)):
        return

    # If already in a virtualenv environment assume all is set up
    venv_path = os.path.split(os.environ.get("VIRTUAL_ENV", ""))
    if venv_path and venv_path[0].endswith(os.path.split(OSS_FUZZ_DIR)[-1]):
        return

    result = sp.run(
        ["python3", "-m", "venv", VENV_DIR],
        check=True,
        capture_output=True,
        stdin=sp.DEVNULL,
        cwd=OSS_FUZZ_DIR,
    )
    result = sp.run(
        [
            f"./{VENV_DIR}/bin/pip",
            "install",
            "-r",
            "infra/build/functions/requirements.txt",
        ],
        check=True,
        cwd=OSS_FUZZ_DIR,
        stdin=sp.DEVNULL,
        capture_output=True,
    )
    if result.returncode:
        logger.info("Failed to postprocess OSS-Fuzz (%s)", OSS_FUZZ_DIR)
        logger.info("stdout: %s", result.stdout)
        logger.info("stderr: %s", result.stderr)


def list_c_cpp_projects() -> list[str]:
    """Returns a list of all c/c++ projects from oss-fuzz."""
    projects = []
    clone_oss_fuzz()
    projects_dir = os.path.join(OSS_FUZZ_DIR, "projects")
    for project in os.listdir(projects_dir):
        project_yaml_path = os.path.join(projects_dir, project, "project.yaml")
        with open(project_yaml_path) as yaml_file:
            config = yaml_file.read()
            if "language: c" in config:
                projects.append(project)
    return sorted(projects)


def get_project_language(project: str) -> str:
    """Returns the |project| language read from its project.yaml."""
    project_yaml_path = os.path.join(OSS_FUZZ_DIR, "projects", project, "project.yaml")
    if not os.path.isfile(project_yaml_path):
        logger.warning(
            "Failed to find the project yaml of %s, assuming it is C++", project
        )
        return "C++"

    with open(project_yaml_path, "r") as benchmark_file:
        data = yaml.safe_load(benchmark_file)
        return data.get("language", "C++")


def get_project_repository(project: str) -> str:
    """Returns the |project| repository read from its project.yaml."""
    project_yaml_path = os.path.join(OSS_FUZZ_DIR, "projects", project, "project.yaml")
    if not os.path.isfile(project_yaml_path):
        logger.warning(
            "Failed to find the project yaml of %s, return empty repository", project
        )
        return ""

    with open(project_yaml_path, "r") as benchmark_file:
        data = yaml.safe_load(benchmark_file)
        return data.get("main_repo", "")


def _get_project_cache_name(project: str) -> str:
    """Gets name of cached container for a project."""
    return f"gcr.io.oss-fuzz.{project}_cache"


def _get_project_cache_image_name(project: str, sanitizer: str) -> str:
    """Gets name of cached Docker image for a project and a respective
    sanitizer."""
    return (
        "us-central1-docker.pkg.dev/oss-fuzz/oss-fuzz-gen/"
        f"{project}-ofg-cached-{sanitizer}"
    )


def _has_cache_build_script(project: str) -> bool:
    """Checks if a project has cached fuzzer build script."""
    cached_build_script = os.path.join("fuzzer_build_script", project)
    return os.path.isfile(cached_build_script)


def _prepare_image_cache(project: str) -> bool:
    """Prepares cached images of fuzzer build containers."""
    # Only create a cached image if we have a post-build build script
    if not _has_cache_build_script(project):
        logger.info("No cached script for %s", project)
        return False
    logger.info("%s has a cached build script", project)

    cached_container_name = _get_project_cache_name(project)
    adjusted_env = os.environ | {"OSS_FUZZ_SAVE_CONTAINERS_NAME": cached_container_name}

    logger.info("Creating a cached images")
    for sanitizer in ["address", "coverage"]:
        if is_image_cached(project, sanitizer):
            logger.info(
                "%s::%s is already cached, reusing existing cache.", project, sanitizer
            )
            continue

        # Pull the cache first
        pull_cmd = ["docker", "pull", _get_project_cache_image_name(project, sanitizer)]
        try:
            sp.run(pull_cmd, check=True)
            logger.info("Successfully pulled cache image for %s", project)
        except sp.CalledProcessError:
            logger.info("Failed pulling image for %s", project)

        if is_image_cached(project, sanitizer):
            logger.info("pulled image for %s::%s", project, sanitizer)
            continue

        # If pull did not work, create cached image by building using OSS-Fuzz
        # with set variable. Fail if this does not work.
        command = [
            "python3",
            "infra/helper.py",
            "build_fuzzers",
            project,
            "--sanitizer",
            sanitizer,
        ]
        try:
            sp.run(command, cwd=OSS_FUZZ_DIR, env=adjusted_env, check=True)
        except sp.CalledProcessError:
            logger.info("Failed to build fuzzer for %s.", project)
            return False

        # Commit the container to an image
        cached_image_name = _get_project_cache_image_name(project, sanitizer)

        command = ["docker", "commit", cached_container_name, cached_image_name]
        try:
            sp.run(command, check=True)
        except sp.CalledProcessError:
            logger.info("Could not rename image.")
            return False
        logger.info("Created cached image %s", cached_image_name)

        # Delete the container we created
        command = ["docker", "container", "rm", cached_container_name]
        try:
            sp.run(command, check=True)
        except sp.CalledProcessError:
            logger.info("Could not rename image.")
    return True


def prepare_cached_images(experiment_targets: list[benchmarklib.Benchmark]) -> None:
    """Builds cached Docker images for a set of targets."""
    all_projects = set()
    for benchmark in experiment_targets:
        all_projects.add(benchmark.project)

    logger.info("Preparing cache for %d projects", len(all_projects))

    for project in all_projects:
        _prepare_image_cache(project)


def is_image_cached(project_name: str, sanitizer: str) -> bool:
    """Checks whether a project has a cached Docker image post fuzzer
    building."""
    cached_image_name = _get_project_cache_image_name(project_name, sanitizer)
    try:
        sp.run(
            ["docker", "manifest", "inspect", cached_image_name],
            check=True,
            stdin=sp.DEVNULL,
            stdout=sp.DEVNULL,
            stderr=sp.STDOUT,
        )
        return True
    except sp.CalledProcessError:
        return False


def rewrite_project_to_cached_project(
    project_name: str, generated_project: str, sanitizer: str
) -> None:
    """Rewrites Dockerfile of a project to enable cached build scripts."""
    cached_image_name = _get_project_cache_image_name(project_name, sanitizer)
    generated_project_folder = os.path.join(OSS_FUZZ_DIR, "projects", generated_project)

    cached_dockerfile = os.path.join(
        generated_project_folder, f"Dockerfile_{sanitizer}_cached"
    )
    if os.path.isfile(cached_dockerfile):
        logger.info("Already converted")
        return

    # Check if there is an original Dockerfile, because we should use that in
    # case,as otherwise the "Dockerfile" may be a copy of another sanitizer.
    original_dockerfile = os.path.join(generated_project_folder, "Dockerfile_original")
    if not os.path.isfile(original_dockerfile):
        dockerfile = os.path.join(generated_project_folder, "Dockerfile")
        shutil.copy(dockerfile, original_dockerfile)

    with open(original_dockerfile, "r") as f:
        docker_content = f.read()

    arg_line = "ARG CACHE_IMAGE=" + cached_image_name
    docker_content = arg_line + "\n" + docker_content
    docker_content = re.sub(
        r"FROM gcr.io/oss-fuzz-base/base-builder.*", "FROM $CACHE_IMAGE", docker_content
    )

    # Now comment out everything except:
    # - The first FROM.
    # - The ARG we just added.
    # - The last 2 COPY commands (for the build script and the target we added).
    arg_line = -1
    from_line = -1
    copy_fuzzer_line = -1
    copy_build_line = -1

    for line_idx, line in enumerate(docker_content.split("\n")):
        if line.startswith("ARG") and arg_line == -1:
            arg_line = line_idx
        if line.startswith("FROM") and from_line == -1:
            from_line = line_idx
        if line.startswith("COPY"):
            copy_fuzzer_line = copy_build_line
            copy_build_line = line_idx

    lines_to_keep = {arg_line, from_line, copy_fuzzer_line, copy_build_line}
    new_content = ""
    for line_idx, line in enumerate(docker_content.split("\n")):
        if line_idx not in lines_to_keep:
            new_content += f"# {line}\n"
        else:
            new_content += f"{line}\n"

    # Overwrite the existing one
    with open(cached_dockerfile, "w") as f:
        f.write(new_content)


def prepare_build(project_name, sanitizer, generated_project):
    """Prepares the correct Dockerfile to be used for cached builds."""
    generated_project_folder = os.path.join(OSS_FUZZ_DIR, "projects", generated_project)
    if not ENABLE_CACHING:
        return
    dockerfile_to_use = os.path.join(generated_project_folder, "Dockerfile")
    original_dockerfile = os.path.join(generated_project_folder, "Dockerfile_original")
    if is_image_cached(project_name, sanitizer):
        logger.info("Using cached dockerfile")
        cached_dockerfile = os.path.join(
            generated_project_folder, f"Dockerfile_{sanitizer}_cached"
        )
        shutil.copy(cached_dockerfile, dockerfile_to_use)
    else:
        logger.info("Using original dockerfile")
        shutil.copy(original_dockerfile, dockerfile_to_use)


def _build_image(project_name: str) -> str:
    """Builds project image in OSS-Fuzz"""
    adjusted_env = os.environ | {"FUZZING_LANGUAGE": get_project_language(project_name)}
    command = ["python3", "infra/helper.py", "build_image", "--pull", project_name]
    try:
        sp.run(
            command,
            cwd=OSS_FUZZ_DIR,
            env=adjusted_env,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
            check=True,
        )
        logger.info("Successfully build project image for %s", project_name)
        return f"gcr.io/oss-fuzz/{project_name}"
    except sp.CalledProcessError as e:
        logger.error(
            "Failed to build project image for %s: %s",
            project_name,
            e.stderr.decode("utf-8"),
        )
        return ""


def rectify_docker_tag(docker_tag: str) -> str:
    # Replace "::" and any character not \w, _, or . with "-".
    valid_docker_tag = re.sub(r"::", "-", docker_tag)
    valid_docker_tag = re.sub(r"[^\w_.]", "-", valid_docker_tag)
    # Docker fails with tags containing -_ or _-.
    valid_docker_tag = re.sub(r"[-_]{2,}", "-", valid_docker_tag)
    return valid_docker_tag


def create_ossfuzz_project(
    benchmark: benchmarklib.Benchmark, generated_oss_fuzz_project: str
) -> str:
    """Creates an OSS-Fuzz project by replicating an existing project."""
    generated_project_path = os.path.join(
        OSS_FUZZ_DIR, "projects", generated_oss_fuzz_project
    )
    if os.path.exists(generated_project_path):
        logger.info("Project %s already exists.", generated_project_path)
        return generated_project_path

    oss_fuzz_project_path = os.path.join(OSS_FUZZ_DIR, "projects", benchmark.project)
    shutil.copytree(oss_fuzz_project_path, generated_project_path)
    return generated_project_path


def prepare_project_image(benchmark: benchmarklib.Benchmark) -> str:
    """Prepares original image of the |project|'s fuzz target build container."""
    project = benchmark.project
    image_name = f"gcr.io/oss-fuzz/{project}"
    generated_oss_fuzz_project = f"{benchmark.id}-{uuid.uuid4().hex}"
    generated_oss_fuzz_project = rectify_docker_tag(generated_oss_fuzz_project)
    create_ossfuzz_project(benchmark, generated_oss_fuzz_project)

    if not ENABLE_CACHING:
        logger.warning("Disabled caching when building image for %s", project)
    elif is_image_cached(project, "address"):
        logger.info("Will use cached instance.")
        # Rewrite for caching.
        rewrite_project_to_cached_project(
            project, generated_oss_fuzz_project, "address"
        )
        # Prepare build
        prepare_build(project, "address", generated_oss_fuzz_project)
        # Build the image
        logger.info(
            "Using cached project image for %s: %s",
            generated_oss_fuzz_project,
            image_name,
        )
    else:
        logger.warning("Unable to find cached project image for %s", project)
    return _build_image(generated_oss_fuzz_project)


def create_ossfuzz_project_by_name(
    original_name: str, generated_oss_fuzz_project: str
) -> str:
    """Creates an OSS-Fuzz project by replicating an existing project."""
    generated_project_path = os.path.join(
        OSS_FUZZ_DIR, "projects", generated_oss_fuzz_project
    )
    if os.path.exists(generated_project_path):
        logger.info("Project %s already exists.", generated_project_path)
        return generated_project_path

    oss_fuzz_project_path = os.path.join(OSS_FUZZ_DIR, "projects", original_name)
    shutil.copytree(oss_fuzz_project_path, generated_project_path)
    return generated_project_path


def prepare_project_image_by_name(project_name: str) -> str:
    """Prepares original image of the |project_name|'s fuzz target build
    container."""
    project = project_name
    image_name = f"gcr.io/oss-fuzz/{project}"
    generated_oss_fuzz_project = f"{project_name}-{uuid.uuid4().hex}"
    generated_oss_fuzz_project = rectify_docker_tag(generated_oss_fuzz_project)
    create_ossfuzz_project_by_name(project, generated_oss_fuzz_project)

    if not ENABLE_CACHING:
        logger.warning("Disabled caching when building image for %s", project)
    elif is_image_cached(project, "address"):
        logger.info("Will use cached instance.")
        # Rewrite for caching.
        rewrite_project_to_cached_project(
            project, generated_oss_fuzz_project, "address"
        )
        # Prepare build
        prepare_build(project, "address", generated_oss_fuzz_project)
        # Build the image
        logger.info(
            "Using cached project image for %s: %s",
            generated_oss_fuzz_project,
            image_name,
        )
    else:
        logger.warning("Unable to find cached project image for %s", project)
    return _build_image(generated_oss_fuzz_project)
