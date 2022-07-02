from setuptools import setup

with open("README.md", "r", encoding="utf8") as fh:
    long_description = fh.read()

setup(
    name='sua',
    version='1.0.0.',
    description='Stochastic Unified Assistant (a.k.a SUA)',
    py_modules=['sua'],
    package_dir={'': 'src'},
    long_description=long_description,
    long_description_content_type="text/markdown",
    url='https://https://github.com/kingsman1960/Sua',
    author="Youngwon Cho",
    author_email="youngwon.cho@tum.de",
    license='MIT',
    install_requires=[
        'numpy',
        'matplotlib',
        'datetime',
        'empyrical',
        'quantstats',
        'yfinance',
        'ipython',
        'fpdf',
        'pyportfolioopt'

    ],
)
