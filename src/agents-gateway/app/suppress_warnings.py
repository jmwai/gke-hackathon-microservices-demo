# This module MUST be imported first to suppress Pydantic warnings
# See: https://github.com/google/adk-python/discussions/2521
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
