# General information and tips for FlexMeasures developers

Here are some general information guidelines and tips.
For more in-depth info, you can consult the Readme files in sub-packages.

## Adding a configuration variable

A new configuration variable needs to be mentioned in `utils/config_defaults.py` in the `Config` class.
Think about if there is a useful default and also what defaults make sense in different environments (see subclasses of `Config`).
If no defaults make sense, simply use `None` as a value.

You then probably need to update config files that are in use, e.g. `development_config.py` (if you have used `None` in at least one environment).
The values for each environment are set in those files. Note that they might live on a server. Also note that they are not kept in git.


## Auto-formatting

We use [Black](https://github.com/ambv/black) to format our Python code and thus find real problems faster.
`Black` can be installed in your editor, but we also use it as a pre-commit hook. To activate that behaviour, do:

    pip install pre-commit
    pre-commit install

in your virtual environment.

Now each git commit will first run `black --diff` over the files affected by the commit
(`pre-commit` will install `black` into its own structure on the first run).
If `black` proposes to edit any file, the commit is aborted (saying that it "failed"), 
and the proposed changes are printed for you to review.

With `git ls-files -m | grep ".py" | xargs black` you can apply the formatting, 
and make them part of your next commit (`git ls-files` cannot list added files,
so they need to be black-formatted separately).


## Hint: Notebooks

If you edit notebooks, make sure results do not end up in git:

    conda install -c conda-forge nbstripout
    nbstripout --install

(on Windows, maybe you need to look closer at https://github.com/kynan/nbstripout)


## Hint: Quickstart for development

I added this to my ~/.bashrc, so I only need to type `flexmeasures` to get started (all paths depend on your local environment, of course):

    addssh(){
        eval `ssh-agent -s`
        ssh-add ~/.ssh/id_bitbucket
    }
    flexmeasures(){
        addssh
        cd ~/flexmeasures  
        git pull  # do not use if any production-like app runs from the git code                                                                                                                                                                     
        workon flexmeasures-venv  # this depends on how you created your virtual environment
    }

