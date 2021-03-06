import argparse
import logging

import hail as hl
from gnomad.sample_qc.sex import adjusted_sex_ploidy_expr
from gnomad.utils.annotations import (annotate_freq, bi_allelic_site_inbreeding_expr, faf_expr, get_adj_expr,
                                      pop_max_expr, qual_hist_expr)

from gnomad_qc.v3.resources.annotations import freq
from gnomad_qc.v3.resources.basics import get_gnomad_v3_mt
from gnomad_qc.v3.resources.meta import meta

logging.basicConfig(level=logging.INFO, format='%(asctime)s: %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')
logger = logging.getLogger("gnomAD_frequency_data")
logger.setLevel(logging.INFO)

POPS_TO_REMOVE_FOR_POPMAX = {'asj', 'fin', 'oth', 'ami'}


def main(args):
    hl.init(log='/frequency_data_generation.log', default_reference='GRCh38')

    logger.info("Reading sparse MT and metadata table...")
    mt = get_gnomad_v3_mt(key_by_locus_and_alleles=True)
    meta_ht = meta.ht().select('pop', 'sex', 'project_id', 'release', 'sample_filters')

    if args.test:
        logger.info("Filtering to chr20:1-1000000")
        mt = hl.filter_intervals(mt, [hl.parse_locus_interval('chr20:1-1000000')])

    mt = hl.experimental.sparse_split_multi(mt, filter_changed_loci=True)

    logger.info("Annotating sparse MT with metadata...")
    mt = mt.annotate_cols(meta=meta_ht[mt.s])
    mt = mt.filter_cols(mt.meta.release)
    samples = mt.count_cols()
    logger.info(f"Running frequency table prep and generation pipeline on {samples} samples")

    logger.info("Computing adj and sex adjusted genotypes.")
    mt = mt.annotate_entries(
        GT=adjusted_sex_ploidy_expr(mt.locus, mt.GT, mt.meta.sex),
        adj=get_adj_expr(mt.GT, mt.GQ, mt.DP, mt.AD)
    )

    logger.info("Densify-ing...")
    mt = hl.experimental.densify(mt)
    mt = mt.filter_rows(hl.len(mt.alleles) > 1)

    logger.info("Setting het genotypes at sites with >1% AF (using v3.0 frequencies) and > 0.9 AB to homalt...")
    # hotfix for depletion of homozygous alternate genotypes
    # Using v3.0 AF to avoid an extra frequency calculation
    # TODO: Using previous callset AF works for small incremental changes to a callset, but we need to revisit for large increments
    freq_ht = freq.versions["3"].ht()
    freq_ht = freq_ht.select(AF=freq_ht.freq[0].AF)

    mt = mt.annotate_entries(
        GT=hl.cond(
            (freq_ht[mt.row_key].AF > 0.01)
            & mt.GT.is_het()
            & (mt.AD[1] / mt.DP > 0.9),
            hl.call(1, 1),
            mt.GT,
        )
    )

    logger.info("Calculating InbreedingCoefficient...")
    # NOTE: This is not the ideal location to calculate this, but added here to avoid another densify
    mt = mt.annotate_rows(InbreedingCoeff=bi_allelic_site_inbreeding_expr(mt.GT))

    logger.info("Generating frequency data...")
    mt = annotate_freq(
        mt,
        sex_expr=mt.meta.sex,
        pop_expr=mt.meta.pop
    )

    # Select freq, FAF and popmax
    faf, faf_meta = faf_expr(mt.freq, mt.freq_meta, mt.locus, POPS_TO_REMOVE_FOR_POPMAX)
    mt = mt.select_rows(
        'InbreedingCoeff',
        'freq',
        faf=faf,
        popmax=pop_max_expr(mt.freq, mt.freq_meta, POPS_TO_REMOVE_FOR_POPMAX)
    )
    mt = mt.annotate_globals(faf_meta=faf_meta)

    # Annotate quality metrics histograms, as these also require densifying
    mt = mt.annotate_rows(
        **qual_hist_expr(mt.GT, mt.GQ, mt.DP, mt.AD)
    )

    logger.info("Writing out frequency data...")
    if args.test:
        mt.rows().write("gs://gnomad-tmp/gnomad_freq/chr20_1_1000000_freq.ht", overwrite=True)
    else:
        mt.rows().write(freq.path, overwrite=args.overwrite)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', help='Runs a test on chr20:1-1000000', action='store_true')
    parser.add_argument('--overwrite', help='Overwrites existing files', action='store_true')

    main(parser.parse_args())
