import joblib
import torch.nn.functional as F
import torch
import torch.nn as nn
import json
import pandas as pd
import os
from typing import Optional, List, Dict, Any
from crewai.tools import tool


class CVAE(nn.Module):
    """
    Conditional Variational Autoencoder (CVAE) for glass composition generation.
    
    This model generates glass compositions conditioned on optical properties:
    refractive index, Abbe number, and mean dispersion. The output contains
    elemental/component ratios plus the glass transition temperature (Tg).
    """
    def __init__(self, cond_dim=3, output_dim=77, latent_dim=10):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(output_dim + cond_dim, 128),
            nn.LeakyReLU(0.2),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.LeakyReLU(0.2),
            nn.Dropout(0.2),
            nn.Linear(64, 32),
            nn.LeakyReLU(0.2),
            nn.Dropout(0.2)
        )
        self.fc_mu = nn.Linear(32, latent_dim)
        self.fc_logvar = nn.Linear(32, latent_dim)

        self.decoder = nn.Sequential(
            nn.Linear(latent_dim + cond_dim, 64),
            nn.LeakyReLU(0.2),
            nn.Dropout(0.2),
            nn.Linear(64, 128),
            nn.LeakyReLU(0.2),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.LeakyReLU(0.2),
            nn.Dropout(0.2),
            nn.Linear(64, output_dim),
            nn.LeakyReLU(0.2)
        )

    def reparameterize(self, mu, logvar):
        """
        Reparameterization trick for VAE training.
        
        Args:
            mu: Mean of the latent distribution
            logvar: Log variance of the latent distribution
            
        Returns:
            Sampled latent vector
        """
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def forward(self, x, c):
        """
        Forward pass through the CVAE.
        
        Args:
            x: Input composition
            c: Conditioning parameters (optical properties)
            
        Returns:
            Tuple of (reconstructed_x, mu, logvar)
        """
        x_cond = torch.cat([x, c], dim=1)
        h = self.encoder(x_cond)
        mu = self.fc_mu(h)
        logvar = self.fc_logvar(h)
        z = self.reparameterize(mu, logvar)
        z_cond = torch.cat([z, c], dim=1)
        return self.decoder(z_cond), mu, logvar


# Global variables for lazy loading (defined after CVAE class)
_device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
_model: Optional[CVAE] = None
_scaler: Optional[Any] = None
_element_list: Optional[List[str]] = None

# Dataset statistics for handling missing parameters
# Mean values calculated from training dataset
_PARAM_MEAN = {
    'refractive_index': 1.58,
    'abbe_number': 46.5,
    'mean_dispersion': 0.0126
}

# Parameter constraints for validation
_PARAM_RANGES = {
    'refractive_index': (1.45, 1.85),
    'abbe_number': (20, 80),
    'mean_dispersion': (0.005, 0.03)
}


def get_model() -> CVAE:
    """
    Lazy load the pre-trained CVAE model.
    
    Returns:
        Loaded CVAE model in evaluation mode
    """
    global _model
    if _model is None:
         model_path = os.path.join('data', 'models', 'cvae_model.pth')
         # Add CVAE class to main module's globals to handle pickling from __main__
         import sys
         if 'CVAE' not in sys.modules['__main__'].__dict__:
             sys.modules['__main__'].CVAE = CVAE
         
         # In PyTorch 2.6+, weights_only defaults to True which doesn't allow unpickling custom classes
         # Since we trust this local model file, we explicitly set weights_only=False
         loaded_data = torch.load(model_path, map_location=_device, weights_only=False)
         
         if isinstance(loaded_data, CVAE):
             # File contains the entire model
             _model = loaded_data.to(_device)
         else:
             # File contains just the state dictionary
             _model = CVAE(cond_dim=3, output_dim=77, latent_dim=10).to(_device)
             _model.load_state_dict(loaded_data)
         
         _model.eval()
    return _model


def get_scaler():
    """
    Lazy load the output scaler for denormalization.
    
    Returns:
        Fitted scaler for inverse transformation
    """
    global _scaler
    if _scaler is None:
        scaler_path = os.path.join('data', 'models', 'output_scaler.pkl')
        _scaler = joblib.load(scaler_path)
    return _scaler


def get_element_list() -> List[str]:
    """
    Lazy load the list of elements/components from file.
    
    Returns:
        List of element/component names
    """
    global _element_list
    if _element_list is None:
        element_path = os.path.join('data','models','element_list.json')
        with open(element_path, "r") as f:
            _element_list = json.load(f)
    return _element_list


def inverse_design(
    cvae_model: CVAE,
    c_input: torch.Tensor,
    performance_predictor=None,
    target_c=None,
    num_samples: int = 100,
    top_k: int = 5
) -> pd.DataFrame:
    """
    Generate glass composition candidates using the trained CVAE model.
    
    Args:
        cvae_model: Trained CVAE model
        c_input: Condition tensor of shape [1, cond_dim]
        performance_predictor: Optional performance predictor model
        target_c: Target conditions for evaluation if using performance predictor
        num_samples: Number of candidate samples to generate
        top_k: Number of top candidates to return based on score
        
    Returns:
        DataFrame containing top-k candidates with composition, Tg, and score
    """
    cvae_model.eval()
    with torch.no_grad():
        # Repeat condition for all samples
        c_repeated = c_input.repeat(num_samples, 1)  # [num_samples, cond_dim]
        latent_dim = cvae_model.fc_mu.out_features

        # Sample latent vectors from standard normal distribution
        z = torch.randn(num_samples, latent_dim, device=_device)

        # Decode to get compositions
        z_cond = torch.cat([z, c_repeated], dim=1)
        outputs = cvae_model.decoder(z_cond)  # [num_samples, output_dim]

        if performance_predictor is not None and target_c is not None:
            # Use performance predictor to evaluate candidates against target
            predicted_c = performance_predictor(outputs)
            loss = F.mse_loss(predicted_c, target_c.repeat(num_samples, 1), reduction='none')
            scores = loss.mean(dim=1)  # Average MSE per sample
        else:
            # Without predictor, score based on distance from mean
            scores = torch.norm(outputs - outputs.mean(dim=0), dim=1)

        # Select top-k candidates with lowest scores
        topk_indices = torch.topk(-scores, top_k).indices
        top_outputs = outputs[topk_indices]
        top_scores = scores[topk_indices]

        # Inverse transform to get original scale
        scaler = get_scaler()
        top_outputs_np = top_outputs.cpu().numpy()
        top_outputs_orig = scaler.inverse_transform(top_outputs_np)

        # Extract composition (all except last column which is Tg)
        composition = top_outputs_orig[:, :-1]
        composition_sum = composition.sum(axis=1, keepdims=True)
        composition_normalized = composition / (composition_sum + 1e-8)  # Prevent division by zero

        # Update with normalized compositions
        top_outputs_orig[:, :-1] = composition_normalized

        # Create result DataFrame
        element_list = get_element_list()
        output_names = element_list + ['Tg']
        result_df = pd.DataFrame(top_outputs_orig, columns=output_names)
        result_df['score'] = top_scores.cpu().numpy()

        return result_df.sort_values('score')


def validate_parameters(
    refractive_index: Optional[float] = None,
    abbe_number: Optional[float] = None,
    mean_dispersion: Optional[float] = None
) -> Dict[str, Any]:
    """
    Validate input parameters against known acceptable ranges.
    
    Args:
        refractive_index: Input refractive index
        abbe_number: Input Abbe number
        mean_dispersion: Input mean dispersion
        
    Returns:
        Dictionary with validation result and messages
    """
    errors = []
    warnings = []
    
    # Check that at least one parameter is provided
    if all(p is None for p in [refractive_index, abbe_number, mean_dispersion]):
        errors.append("At least one parameter must be provided.")
        return {'valid': False, 'errors': errors, 'warnings': warnings}
    
    # Validate each provided parameter
    if refractive_index is not None:
        min_val, max_val = _PARAM_RANGES['refractive_index']
        if not (min_val <= refractive_index <= max_val):
            warnings.append(
                f"Refractive index {refractive_index} is outside typical range [{min_val}, {max_val}]."
            )
    
    if abbe_number is not None:
        min_val, max_val = _PARAM_RANGES['abbe_number']
        if not (min_val <= abbe_number <= max_val):
            warnings.append(
                f"Abbe number {abbe_number} is outside typical range [{min_val}, {max_val}]."
            )
    
    if mean_dispersion is not None:
        min_val, max_val = _PARAM_RANGES['mean_dispersion']
        if not (min_val <= mean_dispersion <= max_val):
            warnings.append(
                f"Mean dispersion {mean_dispersion} is outside typical range [{min_val}, {max_val}]."
            )
    
    return {
        'valid': True,
        'errors': errors,
        'warnings': warnings
    }


def prepare_conditions(
    refractive_index: Optional[float] = None,
    abbe_number: Optional[float] = None,
    mean_dispersion: Optional[float] = None
) -> List[float]:
    """
    Prepare conditions list, using mean values for missing parameters.
    
    Args:
        refractive_index: Refractive index (optional)
        abbe_number: Abbe number (optional)
        mean_dispersion: Mean dispersion (optional)
        
    Returns:
        List of three conditions with defaults filled in
    """
    cond = [
        refractive_index if refractive_index is not None else _PARAM_MEAN['refractive_index'],
        abbe_number if abbe_number is not None else _PARAM_MEAN['abbe_number'],
        mean_dispersion if mean_dispersion is not None else _PARAM_MEAN['mean_dispersion']
    ]
    return cond


@tool("Generate Glass Composition from Optical Properties")
def generate_glass_composition(
    refractive_index: Optional[float] = None,
    abbe_number: Optional[float] = None,
    mean_dispersion: Optional[float] = None,
    num_samples: int = 200,
    top_k: int = 5
) -> str:
    """
    Generate glass composition candidates using a trained Conditional Variational Autoencoder (CVAE) model.
    
    This tool generates glass compositions (element/component percentages) and predicts the glass transition temperature (Tg)
    based on the given optical properties. You can provide any combination of the three optical parameters:
    - Refractive index (nd)
    - Abbe number (νd)
    - Mean dispersion (ΔP)
    
    At least one parameter must be provided. Missing parameters will be filled with dataset average values automatically.

    You are about to call the tool `generate_glass_composition_from_optical_properties`. To prevent API errors, you MUST follow these rules when generating the arguments JSON:

    1.  **Skip Empty/Null Fields:** If a parameter value is empty, unknown, or not provided by the user, **DO NOT include that field** in the JSON arguments. Never pass an empty string `""` for a numeric field.
    2.  **Numeric Validation:** The backend strictly validates data types. The field `mean_dispersion` must be a valid number (float). If you do not have a specific value for `mean_dispersion`, **omit the field entirely** from the arguments object.
    3.  **Correct Example:**
        *   If you only have `refractive_index` and `abbe_number`, send:
            ```json
            {
            "refractive_index": 2.5,
            "abbe_number": 20.0,
            "num_samples": 200,
            "top_k": 5
            }
            ```
    4.  **Forbidden Example:**
        *   Never send:
            ```json
            {
            "refractive_index": 2.5,
            "abbe_number": 20.0,
            "mean_dispersion": "" // This will crash the API
            }
            ```
    
    Args:
        refractive_index: Target refractive index of the glass (typical range: 1.45 to 1.85)
        abbe_number: Target Abbe number of the glass (typical range: 20 to 80)
        mean_dispersion: Target mean dispersion of the glass (typical range: 0.005 to 0.03)
        num_samples: Number of candidate samples to generate (default: 200)
        top_k: Number of top candidates to return (default: 5)
        
    Returns:
        A formatted string containing the top generated glass compositions with their properties.
    """
    # Strict type checking and conversion
    def to_float_strict(val, param_name):
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val.strip())
            except ValueError:
                raise ValueError(f"{param_name} must be a valid floating-point number. Got: '{val}'")
        raise ValueError(f"{param_name} has invalid type {type(val)}. Must be a number.")
    
    try:
        refractive_index = to_float_strict(refractive_index, "refractive_index")
        abbe_number = to_float_strict(abbe_number, "abbe_number")
        mean_dispersion = to_float_strict(mean_dispersion, "mean_dispersion")
        if isinstance(num_samples, str):
            num_samples = int(num_samples.strip())
        if isinstance(top_k, str):
            top_k = int(top_k.strip())
    except ValueError as e:
        return f"Input type error: {str(e)}\n" \
               f"All optical parameters must be numerical floating-point values.\n" \
               f"refractive_index: target refractive index (float)\n" \
               f"abbe_number: target Abbe number (float)\n" \
               f"mean_dispersion: target mean dispersion (float)"
    
    # Validate input parameters
    validation = validate_parameters(refractive_index, abbe_number, mean_dispersion)
    if not validation['valid']:
        error_msg = "Errors in input parameters:\n"
        for error in validation['errors']:
            error_msg += f"- {error}\n"
        return error_msg
    
    # Prepare conditions with defaults for missing parameters
    conditions = prepare_conditions(refractive_index, abbe_number, mean_dispersion)
    
    try:
        # Load model and generate candidates
        model = get_model()
        cond_tensor = torch.tensor(conditions, dtype=torch.float32).unsqueeze(0).to(_device)
        result_df = inverse_design(model, cond_tensor, num_samples=num_samples, top_k=top_k)
        
        # Convert to formatted output string
        output = "# Generated Glass Compositions\n\n"
        output += f"Input conditions:\n"
        if refractive_index is not None:
            output += f"- Refractive Index: **{refractive_index}**\n"
        else:
            output += f"- Refractive Index: *not provided (using dataset mean {_PARAM_MEAN['refractive_index']})*\n"
            
        if abbe_number is not None:
            output += f"- Abbe Number: **{abbe_number}**\n"
        else:
            output += f"- Abbe Number: *not provided (using dataset mean {_PARAM_MEAN['abbe_number']})*\n"
            
        if mean_dispersion is not None:
            output += f"- Mean Dispersion: **{mean_dispersion}**\n"
        else:
            output += f"- Mean Dispersion: *not provided (using dataset mean {_PARAM_MEAN['mean_dispersion']})*\n"
        
        # Add any validation warnings
        if validation['warnings']:
            output += "\n### Warnings:\n"
            for warning in validation['warnings']:
                output += f"- {warning}\n"
        
        # Format each candidate
        output += f"\n## Top {len(result_df)} Candidates:\n\n"
        
        for i, (_, row) in enumerate(result_df.iterrows(), 1):
            output += f"### Candidate {i}\n"
            output += f"- **Predicted Tg**: {row['Tg']:.1f} °C\n"
            output += f"- **Score**: {row['score']:.4f} (lower is better)\n"
            output += "\n**Composition (molar percentage):**\n"
            
             # List ALL components (even with low concentration) as requested
            element_list = get_element_list()
            all_comps = []
            for elem in element_list:
                val = row[elem]
                all_comps.append(f"  - {elem}: {val:.2f}%")
             
            output += "\n".join(all_comps)
            output += "\n\n"
        
        return output
        
    except Exception as e:
        return f"Error during glass composition generation: {str(e)}"