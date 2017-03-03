from __future__ import absolute_import, division, print_function
import numpy as np
import pandas as pd
import scipy.optimize as opt
from scipy.special import erf
from .due import due, Doi

from nilearn import datasets, plotting
from nilearn.input_data import NiftiLabelMasker, NiftiMapsMasker
from nilearn.connectome import ConnectivityMeasure

import h5py
import os

def get_atlas(name):
    if name == "destrieux_2009":
        atlas = datasets.fetch_atlas_destrieux_2009()
        atlas_filename = atlas['maps']
    elif name == "harvard_oxford":
        atlas = datasets.fetch_atlas_harvard_oxford("cort-maxprob-thr25-2mm")
        atlas_filename = atlas['maps']
    elif name == "aal":
        atlas = datasets.fetch_atlas_aal()
        atlas_filename = atlas['maps']
    elif name == "smith_2009":
        atlas = datasets.fetch_atlas_smith_2009()
        atlas_filename = atlas['rsn70']
    else:
        raise ValueError('Atlas name unkown')
    return atlas_filename

def extract_correlation_matrix(data_filename, confounds_filename, atlas_name = "destrieux_2009", correlation_type = 'correlation'):
    
    atlas_filename = get_atlas(atlas_name)
    #labels = atlas['labels']
    
    masker = NiftiLabelsMasker(labels_img=atlas_filename, standardize=True)
    time_series = masker.fit_transform(data_filename,
                                   confounds= confounds_filename)
    correlation_measure = ConnectivityMeasure(kind=correlation_type)
    correlation_matrix = correlation_measure.fit_transform([time_series])[0]  
    
    return correlation_matrix

def compute_matrices(data_volumes, confounds, subject_ids, runs, output_file = "embeddings.hdf5"):
    #get confounds
    #get data files
    
#    data_name = data.func[0]
#    confounds_name = data.confounds
    f = h5py.File(output_file, "w")
    
    for i in xrange(len(data_volumes)):
        subject = subject_ids[i]
        run = runs[i]
        data_name = data_volumes[i]
        confounds_name = confounds[i]
        for atlas in ["destrieux_2009", "harvard_oxford", "aal"]:
            print "using atlas "+atlas
            for affinity_measure in ["correlation", "partial correlation", "precision"]:
                print "computing "+affinity_measure+" matrix"
                sgrp = f.create_group(subject+"/"+run+"/"+atlas+"/"+affinity_measure)
                correlation_matrix = extract_correlation_matrix(data_name, confounds_name, atlas_name = atlas, correlation_type=affinity_measure)
                dset = sgrp.create_dataset("affinity_matrix", correlation_matrix.shape, dtype=correlation_matrix.dtype)
                dset[...]=correlation_matrix
    f.close()

# Use duecredit (duecredit.org) to provide a citation to relevant work to
# be cited. This does nothing, unless the user has duecredit installed,
# And calls this with duecredit (as in `python -m duecredit script.py`):
due.cite(Doi("10.1167/13.9.30"),
         description="Template project for small scientific Python projects",
         tags=["reference-implementation"],
         path='diffusion_embed')


def compute_nearest_neighbor_graph(K, n_neighbors=50):
    idx = np.argsort(K, axis=1)
    col = idx[:, -n_neighbors:].flatten()
    row = (np.array(range(K.shape[0]))[:, None] * np.ones((1, n_neighbors))).flatten().astype(int)
    A1 = sps.csr_matrix((np.ones((len(row))), (row, col)), shape=K.shape)
    A1 = (A1 + A1.transpose()) > 0
    idx1 = A1.nonzero()
    K = sps.csr_matrix((K.flat[idx1[0]*A1.shape[1] + idx1[1]],
                        A1.indices, A1.indptr))
    return K


def compute_affinity(X, method='markov', eps=None):
    import numpy as np
    from sklearn.metrics import pairwise_distances
    D = pairwise_distances(X, metric='euclidean')
    if eps is None:
        k = int(max(2, np.round(D.shape[0] * 0.01)))
        eps = 2 * np.median(np.sort(D, axis=0)[k+1, :])**2
    if method == 'markov':
        affinity_matrix = np.exp(-(D * D) / eps)
    elif method == 'cauchy':
        affinity_matrix = 1./(D * D + eps)
    return affinity_matrix

"""Generate a diffusion map embedding
"""

def compute_markov_matrix(L, alpha=0.5, diffusion_time=0, skip_checks=False, overwrite=False):
    import numpy as np
    import scipy.sparse as sps

    use_sparse = False
    if sps.issparse(L):
        use_sparse = True

    if not skip_checks:
        from sklearn.manifold.spectral_embedding_ import _graph_is_connected
        if not _graph_is_connected(L):
            raise ValueError('Graph is disconnected')

    ndim = L.shape[0]
    if overwrite:
        L_alpha = L
    else:
        L_alpha = L.copy()

    if alpha > 0:
        # Step 2
        d = np.array(L_alpha.sum(axis=1)).flatten()
        d_alpha = np.power(d, -alpha)
        if use_sparse:
            L_alpha.data *= d_alpha[L_alpha.indices]
            L_alpha = sps.csr_matrix(L_alpha.transpose().toarray())
            L_alpha.data *= d_alpha[L_alpha.indices]
            L_alpha = sps.csr_matrix(L_alpha.transpose().toarray())
        else:
            L_alpha = d_alpha[:, np.newaxis] * L_alpha
            L_alpha = L_alpha * d_alpha[np.newaxis, :]

    # Step 3
    d_alpha = np.power(np.array(L_alpha.sum(axis=1)).flatten(), -1)
    if use_sparse:
        L_alpha.data *= d_alpha[L_alpha.indices]
    else:
        L_alpha = d_alpha[:, np.newaxis] * L_alpha

    return L_alpha

def compute_diffusion_map(L, alpha=0.5, n_components=None, diffusion_time=0,
                          skip_checks=False, overwrite=False):
    """Compute the diffusion maps of a symmetric similarity matrix
        L : matrix N x N
           L is symmetric and L(x, y) >= 0
        alpha: float [0, 1]
            Setting alpha=1 and the diffusion operator approximates the
            Laplace-Beltrami operator. We then recover the Riemannian geometry
            of the data set regardless of the distribution of the points. To
            describe the long-term behavior of the point distribution of a
            system of stochastic differential equations, we can use alpha=0.5
            and the resulting Markov chain approximates the Fokker-Planck
            diffusion. With alpha=0, it reduces to the classical graph Laplacian
            normalization.
        n_components: int
            The number of diffusion map components to return. Due to the
            spectrum decay of the eigenvalues, only a few terms are necessary to
            achieve a given relative accuracy in the sum M^t.
        diffusion_time: float >= 0
            use the diffusion_time (t) step transition matrix M^t
            t not only serves as a time parameter, but also has the dual role of
            scale parameter. One of the main ideas of diffusion framework is
            that running the chain forward in time (taking larger and larger
            powers of M) reveals the geometric structure of X at larger and
            larger scales (the diffusion process).
            t = 0 empirically provides a reasonable balance from a clustering
            perspective. Specifically, the notion of a cluster in the data set
            is quantified as a region in which the probability of escaping this
            region is low (within a certain time t).
        skip_checks: bool
            Avoid expensive pre-checks on input data. The caller has to make
            sure that input data is valid or results will be undefined.
        overwrite: bool
            Optimize memory usage by re-using input matrix L as scratch space.
        References
        ----------
        [1] https://en.wikipedia.org/wiki/Diffusion_map
        [2] Coifman, R.R.; S. Lafon. (2006). "Diffusion maps". Applied and
        Computational Harmonic Analysis 21: 5-30. doi:10.1016/j.acha.2006.04.006
    """

    M = compute_markov_matrix(L, alpha, diffusion_time, skip_checks, overwrite)

    from scipy.sparse.linalg import eigsh, eigs
    import numpy as np

    ndim = L.shape[0]

    # Step 4
    func = eigs
    if n_components is not None:
        lambdas, vectors = func(M, k=n_components + 1)
    else:
        lambdas, vectors = func(M, k=max(2, int(np.sqrt(ndim))))
    del M

    if func == eigsh:
        lambdas = lambdas[::-1]
        vectors = vectors[:, ::-1]
    else:
        lambdas = np.real(lambdas)
        vectors = np.real(vectors)
        lambda_idx = np.argsort(lambdas)[::-1]
        lambdas = lambdas[lambda_idx]
        vectors = vectors[:, lambda_idx]

    # Step 5

    psi = vectors/vectors[:, [0]]
    olambdas = lambdas.copy()

    if diffusion_time == 0:
        lambdas = lambdas[1:] / (1 - lambdas[1:])
    else:
        lambdas = lambdas[1:] ** float(diffusion_time)
    lambda_ratio = lambdas/lambdas[0]
    threshold = max(0.05, lambda_ratio[-1])

    n_components_auto = np.amax(np.nonzero(lambda_ratio > threshold)[0])
    n_components_auto = min(n_components_auto, ndim)
    if n_components is None:
        n_components = n_components_auto
    embedding = psi[:, 1:(n_components + 1)] * lambdas[:n_components][None, :]

    result = dict(lambdas=lambdas, orig_lambdas = olambdas, vectors=vectors,
                  n_components=n_components, diffusion_time=diffusion_time,
                  n_components_auto=n_components_auto)
    return embedding, result

def embed_data(data_file_name):
    f = h5py.File(data_file_name,'r+')
    for subject in f.keys():
        for run in f[subject].keys():
            for atlas in f[subject][run].keys():
                for corr_type in f[subject][run][atlas].keys():
                    mat = f[subject][run][atlas][corr_type]['affinity_matrix'][()]
                    affinity_matrix = compute_affinity(mat)
                    embedding, res = compute_diffusion_map(affinity_matrix)
                    v=res['vectors']
                    lambdas = res['orig_lambdas']
                    grp = f[subject][run][atlas][corr_type]
                    dset = grp.create_dataset("lambdas", lambdas.shape, dtype=lambdas.dtype)
                    dset[...]=lambdas
                    dset = grp.create_dataset("v", v.shape, dtype=v.dtype)
                    dset[...]=v
    f.close()



