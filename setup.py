from setuptools import setup, find_packages

setup(
    name="ads-science-analytics-platform",
    version="1.0.0",
    description="End-to-end analytics platform for ad auction intelligence, KPI monitoring, and supply optimization.",
    author="Eden Funk",
    python_requires=">=3.10",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "numpy>=1.26.0",
        "pandas>=2.1.0",
        "scipy>=1.11.0",
        "scikit-learn>=1.3.0",
        "joblib>=1.3.0",
        "streamlit>=1.28.0",
        "plotly>=5.17.0",
    ],
    extras_require={
        "dev": ["pytest", "pytest-cov", "ruff", "black"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
