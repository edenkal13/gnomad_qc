import hail as hl
from gnomad.resources.resource_utils import (MatrixTableResource,
                                             VersionedMatrixTableResource)

from gnomad_qc.v3.resources.constants import CURRENT_RELEASE
from gnomad_qc.v3.resources.meta import meta
from gnomad_qc.v3.resources.sample_qc import hard_filtered_samples


def get_gnomad_v3_mt(
    split=False,
    key_by_locus_and_alleles: bool = False,
    remove_hard_filtered_samples: bool = True,
    release_only: bool = False,
    samples_meta: bool = False,
) -> hl.MatrixTable:
    """
    Wrapper function to get gnomAD data with desired filtering and metadata annotations

    :param split: Perform split on MT - Note: this will perform a split on the MT rather than grab an already split MT
    :param key_by_locus_and_alleles: Whether to key the MatrixTable by locus and alleles (only needed for v3)
    :param remove_hard_filtered_samples: Whether to remove samples that failed hard filters (only relevant after sample QC)
    :param release_only: Whether to filter the MT to only samples available for release (can only be used if metadata is present)
    :param samples_meta: Whether to add metadata to MT in 'meta' column
    :return: gnomAD v3 dataset with chosen annotations and filters
    """
    mt = gnomad_v3_genotypes.mt()
    if key_by_locus_and_alleles:
        mt = hl.MatrixTable(
            hl.ir.MatrixKeyRowsBy(mt._mir, ["locus", "alleles"], is_sorted=True)  # Prevents hail from running sort on genotype MT which is already sorted by a unique locus 
        )

    if remove_hard_filtered_samples:
        mt = mt.filter_cols(hl.is_missing(hard_filtered_samples.ht()[mt.col_key]))

    if samples_meta:
        mt = mt.annotate_cols(meta=meta.ht()[mt.col_key])

        if release_only:
            mt = mt.filter_cols(mt.meta.release)

    elif release_only:
        mt = mt.filter_cols(meta.ht()[mt.col_key].release)

    if split:
        mt = mt.annotate_rows(
            n_unsplit_alleles=hl.len(mt.alleles),
            mixed_site=(hl.len(mt.alleles) > 2)
            & hl.any(lambda a: hl.is_indel(mt.alleles[0], a), mt.alleles[1:])
            & hl.any(lambda a: hl.is_snp(mt.alleles[0], a), mt.alleles[1:]),
        )
        mt = hl.experimental.sparse_split_multi(mt, filter_changed_loci=True)

    return mt


gnomad_v3_genotypes = VersionedMatrixTableResource(
    CURRENT_RELEASE,
    {
        "3": MatrixTableResource(
            "gs://gnomad/raw/hail-0.2/mt/genomes_v3/gnomad_genomes_v3.repartitioned.mt"
        ),
        "3.1": MatrixTableResource(
            "gs://gnomad/raw/genomes/3.1/gnomad_v3.1_sparse_unsplit.repartitioned.mt"
        ),
    },
)
