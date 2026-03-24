from setuptools import setup


def load_requirements(use_case: str) -> list[str]:
    """
    Loading requirements.

    These are not exactly-pinned versions.
    For the standard packaging (as it should be here), we assume someone is installing FlexMeasures into an existing stack.
    We want to avoid version clashes. That is why we read the .in file for the use case.

    .txt files include the exact pins, and are useful for deployments with
    exactly comparable environments. If you want those, install them before pip-installing FlexMeasures.
    """
    reqs = []
    with open("requirements/%s.in" % use_case, "r") as f:
        reqs = [
            req
            for req in f.read().splitlines()
            if not req.strip() == ""
            and not req.strip().startswith("#")
            and not req.strip().startswith("-c")
            and not req.strip().startswith("--find-links")
        ]
    return reqs


setup(install_requires=load_requirements("app"))
