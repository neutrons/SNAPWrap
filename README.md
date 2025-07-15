# SNAPWrap

**Instrument Scientist Scripting Interface into SNAPRed**

SNAPWrap provides a high-level Python interface for neutron scattering data reduction and analysis for the SNAP (Spallation Neutrons and Pressure) instrument at Oak Ridge National Laboratory.

## 🚀 Quick Start

### 1. Install PIXI (Package Manager)

PIXI is a modern package manager that handles all dependencies automatically. Install it with:

```bash
curl -fsSL https://pixi.sh/install.sh | bash
```

**Note**: You may need to restart your terminal or run `source ~/.bashrc` after installation.

### 2. Set Up SNAPWrap

Clone this repository and set up the environment:

```bash
git clone https://github.com/neutrons/SNAPWrap.git
cd SNAPWrap
pixi install
```

The `pixi install` command will automatically:
- Download and install Python and all required packages
- Set up Mantid (neutron data analysis framework)
- Install SNAPRed (SNAP data reduction backend)
- Configure the complete analysis environment

### 3. Start Using SNAPWrap

Activate the environment and start working:

```bash
pixi shell
```

This gives you access to Python with all the neutron analysis tools installed.

## 🧪 Testing Your Installation

Verify everything works correctly:

```bash
pixi run test
```

This runs automated tests to ensure:
- All Python packages import correctly
- Mantid is properly configured
- SNAPRed backend is accessible
- Basic functionality works

## 📦 Available Commands

SNAPWrap provides several pre-configured commands for common tasks:

### Testing and Validation
- **`pixi run test`** - Run all tests to verify your installation works

### Building Packages
- **`pixi run build-pypi`** - Create a Python package (.whl file) for distribution
- **`pixi run build-docs`** - Generate HTML documentation from the source code

### Cleanup
- **`pixi run clean-all`** - Remove all temporary build files and start fresh
- **`pixi run clean-docs`** - Remove only documentation build files
- **`pixi run clean-pypi`** - Remove only Python build files

### Publishing (Maintainers Only)
- **`pixi run publish-pypi`** - Upload the package to PyPI (requires credentials)

## 🔬 Key Features

SNAPWrap provides tools for neutron scattering analysis:

- **Data Reduction Pipeline**: Connect to SNAPRed backend for processing raw neutron data
- **Multiple Export Formats**: Save results as GSAS-II, XYE, or CSV files for further analysis
- **Instrument State Management**: Track detector positions, wavelength, and other instrument settings
- **Advanced Data Masking**: Visual 2D masking tools and automated algorithms for data quality
- **Sample Environment Support**: Handle sample environment equipment (SEE) configurations

## 💻 For Developers

### Development Environment Setup

1. **Clone and Install**:
   ```bash
   git clone https://github.com/neutrons/SNAPWrap.git
   cd SNAPWrap
   pixi install
   ```

2. **Activate Development Environment**:
   ```bash
   pixi shell
   ```

3. **Run Tests During Development**:
   ```bash
   pixi run test
   ```

### Making Changes

The environment includes:
- **Python 3.8+** with scientific computing libraries
- **Mantid Framework** for neutron data analysis
- **SNAPRed** for SNAP-specific data reduction
- **Development Tools**: pytest, pre-commit hooks, code formatting
- **Documentation Tools**: Sphinx for generating docs

### Environment Details

All dependencies are managed through `pyproject.toml`. The environment includes packages from:
- **conda-forge**: Standard scientific Python packages
- **mantid channels**: Specialized neutron analysis software
- **neutrons channels**: ORNL-specific tools

## 🔧 Troubleshooting

### Common Issues

**"Command not found: pixi"**
- Restart your terminal or run `source ~/.bashrc`
- Verify PIXI installed correctly: `pixi --version`

**"Failed to solve dependencies"**
- Ensure you have internet access to download packages
- The installation requires access to specialized conda channels
- Try `pixi clean` then `pixi install` to start fresh

**"Tests fail with import errors"**
- Run `pixi install` to ensure all dependencies are installed
- Check that you're in a `pixi shell` when running commands

### Getting Help

- Check the tests: `pixi run test` shows what's working
- View environment info: `pixi info`
- Contact the development team for instrument-specific issues

## 📋 System Requirements

- **Operating System**: Linux x86_64 (recommended), macOS, or Windows with WSL
- **Internet Connection**: Required for downloading specialized neutron analysis packages
- **Disk Space**: ~2GB for complete environment with all dependencies

## 🤝 Contributing

We welcome contributions! To get started:

1. Fork the repository
2. Set up your development environment with `pixi install`
3. Make your changes
4. Run tests with `pixi run test`
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
