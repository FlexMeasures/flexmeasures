from flask import current_app as app

# from bvp.data.models.forecasting.solar import model1


@app.cli.command()
def solar_model1():
    """Test integration of the ts-forecasting-pipeline"""

    print("Waiting for ts_forecasting_pipeline on the cheeseshop")
    return

    # with app.app_context():
    #    model1()
