from timetomodel import ModelSpecs

from bvp.data.models.forecasting.model_spec_factory import create_init_params


class ChainedModelSpecs(ModelSpecs):
    """Describes a model, how it was trained, and how it fits in the chain of command
    (what model to escalate to if it encounters a problem). Specifically:
    - We create initial parameters for what data to use as features (like certain asset-specific regressors and lags).
    - We initialise a timetomodel.ModelSpecs with these parameters.
    - We set a model so the specs state what algorithm to use (e.g. Random Forest with certain hyperparameters).
    - We give the specs a version and identifier and tell it what specs to fall back on in case of failure.
    """

    def __init__(
        self,
        model,
        version,
        model_identifier,
        fallback_model_search_term,
        library_name: str = None,
        *args,
        **kwargs
    ):
        init_params = create_init_params(*args, **kwargs)
        super().__init__(**init_params)
        self.set_model(model, library_name)
        self.version = version
        self.model_identifier = model_identifier
        self.fallback_model_search_term = fallback_model_search_term
