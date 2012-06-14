# -*- coding: utf-8 -*-

#
# LOFAR Transients Key Project
#
# Bart Scheers, Evert Rol
#
# discovery@transientskp.org
#
import os
import sys
import math
import logging
import monetdb.sql as db
from tkp.config import config
# To do: any way we can get rid of this dependency?
from tkp.sourcefinder.extract import Detection
from .database import ENGINE

AUTOCOMMIT = config['database']['autocommit']
DERUITER_R = config['source_association']['deruiter_radius']
BG_DENSITY = config['source_association']['bg-density']


def insert_dataset(conn, description):
    """Insert dataset with discription as given by argument.

    DB function insertDataset() sets the necessary default values.
    """

    newdsid = None
    try:
        cursor = conn.cursor()
        query = """\
        SELECT insertDataset(%s)
        """
        cursor.execute(query, (description,))
        if not AUTOCOMMIT:
            conn.commit()
        newdsid = cursor.fetchone()[0]
    except db.Error, e:
        logging.warn("Query failed: %s." % query)
        raise
    finally:
        cursor.close()
    return newdsid


def insert_image(conn, dsid, freq_eff, freq_bw, taustart_ts, url):
    """Insert an image for a given dataset with the column values
    given in the argument list.
    """

    newimgid = None
    try:
        cursor = conn.cursor()
        query = """\
        SELECT insertImage(%s, %s, %s, %s, %s)
        """
        cursor.execute(query, (dsid
                              ,freq_eff
                              ,freq_bw
                              ,taustart_ts
                              ,url
                              ))
        newimgid = cursor.fetchone()[0]
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Query failed: %s." % query)
        raise
    finally:
        cursor.close()
    return newimgid


def load_LSM(conn, ira_min, ira_max, idecl_min, idecl_max, cat1="NVSS", cat2="VLSS", cat3="WENSS"):
    #raise NotImplementedError

    try:
        cursor = conn.cursor()
        query = """\
        CALL LoadLSM(%s, %s, %s, %s, %s, %s, %s)
        /*CALL LoadLSM(47, 59, 50, 58, 'NVSS', 'VLSS', 'WENSS')*/
        """
        cursor.execute(query, (ira_min,ira_max,idecl_min,idecl_max,cat1,cat2,cat3))
        #cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed to insert lsm by procedure LoadLSM: %s" % e)
        raise
    finally:
        cursor.close()


# The following set of functions are private to the module
# these are called by insert_extracted_sources(), and should
# only be used that way
def _empty_detections(conn):
    """Empty the detections table

    Initialize the detections table by
    deleting all entries.

    It is used at the beginning and the end
    when detected sources are inserted.
    """

    try:
        cursor = conn.cursor()
        query = """\
        DELETE FROM detections
        """
        cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _insert_into_detections(conn, results):
    """Insert all detections

    Insert all detections, as they are,
    straight into the detection table.

    """

    # TODO: COPY INTO is faster.
    if not results:
        return
    try:
        query = [str(tuple(det)) for det in results]
        query = "INSERT INTO detections VALUES " + ",".join(query)
        conn.cursor().execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        conn.cursor().close()


def _insert_extractedsources(conn, image_id):
    """Insert all extracted sources with their properties

    Insert all detected sources and some derived properties into the
    extractedsources table.

    """

    cursor = conn.cursor()
    try:
        query = """\
        INSERT INTO extractedsources
          (image_id
          ,zone
          ,ra
          ,decl
          ,ra_err
          ,decl_err
          ,semimajor
          ,semiminor
          ,pa
          ,x
          ,y
          ,z
          ,det_sigma
          ,I_peak
          ,I_peak_err
          ,I_int
          ,I_int_err
          )
          SELECT image_id
                ,t0.zone
                ,ra
                ,decl
                ,ra_err
                ,decl_err
                ,semimajor
                ,semiminor
                ,pa
                ,x
                ,y
                ,z
                ,det_sigma
                ,I_peak
                ,I_peak_err
                ,I_int
                ,I_int_err
           FROM (SELECT %s AS image_id
                       ,CAST(FLOOR(ldecl) AS INTEGER) AS zone
                       ,lra AS ra
                       ,ldecl AS decl
                       ,lra_err * 3600 AS ra_err
                       ,ldecl_err * 3600 AS decl_err
                       ,lsemimajor as semimajor
                       ,lsemiminor as semiminor
                       ,lpa as pa
                       ,COS(RADIANS(ldecl)) * COS(RADIANS(lra)) AS x
                       ,COS(RADIANS(ldecl)) * SIN(RADIANS(lra)) AS y
                       ,SIN(RADIANS(ldecl)) AS z
                       ,ldet_sigma AS det_sigma
                       ,lI_peak AS I_peak 
                       ,lI_peak_err AS I_peak_err
                       ,lI_int AS I_int
                       ,lI_int_err AS I_int_err
                   FROM detections
                ) t0
/*               ,node n
          WHERE n.zone = t0.zone */
        """
        cursor.execute(query, (image_id,))
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def insert_extracted_sources(conn, image_id, results):
    """Insert all extracted sources

    Insert the sources that were detected by the Source Extraction
    procedures into the extractedsources table.

    Therefore, we use a temporary table containing the "raw" detections,
    from which the sources will then be inserted into extractedsourtces.
    """

    _empty_detections(conn)
    _insert_into_detections(conn, results)
    _insert_extractedsources(conn, image_id)
    _empty_detections(conn)


# The following set of functions are private to the module;
# these are called by associate_extracted_sources, and should
# only be used in that way
def _empty_temprunningcatalog(conn):
    """Initialize the temporary storage table

    Initialize the temporary table temprunningcatalog which contains
    the current observed sources.
    """

    try:
        cursor = conn.cursor()
        query = """DELETE FROM temprunningcatalog"""
        cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _insert_temprunningcatalog(conn, image_id, deRuiter_r):
    """Select matched sources

    Here we select the extractedsources that have a positional match
    with the sources in the running catalogue table (runningcatalog)
    and those who have will be inserted into the temporary running
    catalogue table (temprunningcatalog).

    Explanation of some columns used in the SQL query:

    - avg_I_peak := average of I_peak
    - avg_I_peak_sq := average of I_peak^2
    - avg_weight_I_peak := average of weight of I_peak, i.e. 1/error^2
    - avg_weighted_I_peak := average of weighted i_peak,
         i.e. average of I_peak/error^2
    - avg_weighted_I_peak_sq := average of weighted i_peak^2,
         i.e. average of I_peak^2/error^2

    This result set might contain multiple associations (1-n,n-1)
    for a single known source in runningcatalog.

    The n-1 assocs will be treated similar as the 1-1 assocs.
    """

    try:
        cursor = conn.cursor()
        # !!TODO!!: Add columns for previous weighted averaged values,
        # otherwise the assoc_r will be biased.
        query = """\
INSERT INTO temprunningcatalog
  (xtrsrc_id
  ,assoc_xtrsrc_id
  ,ds_id
  ,band
  ,datapoints
  ,zone
  ,wm_ra
  ,wm_decl
  ,wm_ra_err
  ,wm_decl_err
  ,avg_wra
  ,avg_wdecl
  ,avg_weight_ra
  ,avg_weight_decl
  ,x
  ,y
  ,z
  ,avg_I_peak
  ,avg_I_peak_sq
  ,avg_weight_peak
  ,avg_weighted_I_peak
  ,avg_weighted_I_peak_sq
  )
  SELECT t0.xtrsrc_id
        ,t0.assoc_xtrsrc_id
        ,t0.ds_id
        ,t0.band
        ,t0.datapoints
        ,CAST(FLOOR(t0.wm_decl/1.0) AS INTEGER)
        ,t0.wm_ra
        ,t0.wm_decl
        ,t0.wm_ra_err
        ,t0.wm_decl_err
        ,t0.avg_wra
        ,t0.avg_wdecl
        ,t0.avg_weight_ra
        ,t0.avg_weight_decl
        ,COS(RADIANS(t0.wm_decl)) * COS(RADIANS(t0.wm_ra))
        ,COS(RADIANS(t0.wm_decl)) * SIN(RADIANS(t0.wm_ra))
        ,SIN(RADIANS(t0.wm_decl))
        ,t0.avg_I_peak
        ,t0.avg_I_peak_sq
        ,t0.avg_weight_peak
        ,t0.avg_weighted_I_peak
        ,t0.avg_weighted_I_peak_sq
    FROM (SELECT rc.xtrsrc_id as xtrsrc_id
                ,x0.xtrsrcid as assoc_xtrsrc_id
                ,im0.ds_id
                ,im0.band
                ,rc.datapoints + 1 AS datapoints
                ,((datapoints * rc.avg_wra + x0.ra /
                  (x0.ra_err * x0.ra_err)) / (datapoints + 1))
                 /
                 ((datapoints * rc.avg_weight_ra + 1 /
                   (x0.ra_err * x0.ra_err)) / (datapoints + 1))
                 AS wm_ra
                ,((datapoints * rc.avg_wdecl + x0.decl /
                  (x0.decl_err * x0.decl_err)) / (datapoints + 1))
                 /
                 ((datapoints * rc.avg_weight_decl + 1 /
                   (x0.decl_err * x0.decl_err)) / (datapoints + 1))
                 AS wm_decl
                ,SQRT(1 / ((datapoints + 1) *
                  ((datapoints * rc.avg_weight_ra +
                    1 / (x0.ra_err * x0.ra_err)) / (datapoints + 1))
                          )
                     ) AS wm_ra_err
                ,SQRT(1 / ((datapoints + 1) *
                  ((datapoints * rc.avg_weight_decl +
                    1 / (x0.decl_err * x0.decl_err)) / (datapoints + 1))
                          )
                     ) AS wm_decl_err
                ,(datapoints * rc.avg_wra + x0.ra / (x0.ra_err * x0.ra_err))
                 / (datapoints + 1) AS avg_wra
                ,(datapoints * rc.avg_wdecl + x0.decl /
                  (x0.decl_err * x0.decl_err))
                 / (datapoints + 1) AS avg_wdecl
                ,(datapoints * rc.avg_weight_ra + 1 /
                  (x0.ra_err * x0.ra_err))
                 / (datapoints + 1) AS avg_weight_ra
                ,(datapoints * rc.avg_weight_decl + 1 /
                  (x0.decl_err * x0.decl_err))
                 / (datapoints + 1) AS avg_weight_decl
                ,(datapoints * rc.avg_I_peak + x0.I_peak)
                 / (datapoints + 1)
                 AS avg_I_peak
                ,(datapoints * rc.avg_I_peak_sq +
                  x0.I_peak * x0.I_peak)
                 / (datapoints + 1)
                 AS avg_I_peak_sq
                ,(datapoints * rc.avg_weight_peak + 1 /
                  (x0.I_peak_err * x0.I_peak_err))
                 / (datapoints + 1)
                 AS avg_weight_peak
                ,(datapoints * rc.avg_weighted_I_peak + x0.I_peak /
                  (x0.I_peak_err * x0.I_peak_err))
                 / (datapoints + 1)
                 AS avg_weighted_I_peak
                ,(datapoints * rc.avg_weighted_I_peak_sq
                  + (x0.I_peak * x0.I_peak) /
                     (x0.I_peak_err * x0.I_peak_err))
                 / (datapoints + 1) AS avg_weighted_I_peak_sq
            FROM runningcatalog rc
                ,extractedsources x0
                ,images im0
           WHERE x0.image_id = %s
             AND x0.image_id = im0.imageid
             AND im0.ds_id = rc.ds_id
             AND rc.zone BETWEEN CAST(FLOOR(x0.decl - 0.025) as INTEGER)
                             AND CAST(FLOOR(x0.decl + 0.025) as INTEGER)
             AND rc.wm_decl BETWEEN x0.decl - 0.025
                                AND x0.decl + 0.025
             AND rc.wm_ra BETWEEN x0.ra - alpha(0.025,x0.decl)
                              AND x0.ra + alpha(0.025,x0.decl)
             AND SQRT(  (x0.ra * COS(RADIANS(x0.decl)) - rc.wm_ra * COS(RADIANS(rc.wm_decl)))
                      * (x0.ra * COS(RADIANS(x0.decl)) - rc.wm_ra * COS(RADIANS(rc.wm_decl)))
                      / (x0.ra_err * x0.ra_err + rc.wm_ra_err * rc.wm_ra_err)
                     + (x0.decl - rc.wm_decl) * (x0.decl - rc.wm_decl)
                      / (x0.decl_err * x0.decl_err + rc.wm_decl_err * rc.wm_decl_err)
                     ) < %s
         ) t0
"""
        cursor.execute(query, (image_id, deRuiter_r/3600.))
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _flag_multiple_counterparts_in_runningcatalog(conn):
    """Flag source with multiple associations

    Before we continue, we first take care of the sources that have
    multiple associations in both directions.

    -1- running-catalogue sources  <- extracted source

    An extracted source has multiple counterparts in the running
    catalogue.  We only keep the ones with the lowest deRuiter_r
    value, the rest we throw away.

    NOTE:

    It is worth considering whether this might be changed to selecting
    the brightest neighbour source, instead of just the closest
    neighbour.

    (There are case [when flux_lim > 10Jy] that the nearest source has
    a lower flux level, causing unexpected spectral indices)
    """

    try:
        cursor = conn.cursor()
        query = """\
        SELECT t1.xtrsrc_id
              ,t1.assoc_xtrsrc_id
          FROM (SELECT trc0.assoc_xtrsrc_id
                      ,MIN(SQRT((x0.ra - rc0.wm_ra) * COS(RADIANS(x0.decl))
                                * (x0.ra - rc0.wm_ra) * COS(RADIANS(x0.decl))
                                / (x0.ra_err * x0.ra_err + rc0.wm_ra_err *
                                   rc0.wm_ra_err)
                               + (x0.decl - rc0.wm_decl) *
                                 (x0.decl - rc0.wm_decl)
                                / (x0.decl_err * x0.decl_err +
                                   rc0.wm_decl_err * rc0.wm_decl_err)
                               )
                          ) AS min_r1
                  FROM temprunningcatalog trc0
                      ,runningcatalog rc0
                      ,extractedsources x0
                 WHERE trc0.assoc_xtrsrc_id IN (SELECT assoc_xtrsrc_id
                                                 FROM temprunningcatalog
                                               GROUP BY assoc_xtrsrc_id
                                               HAVING COUNT(*) > 1
                                              )
                   AND trc0.xtrsrc_id = rc0.xtrsrc_id
                   AND trc0.assoc_xtrsrc_id = x0.xtrsrcid
                GROUP BY trc0.assoc_xtrsrc_id
               ) t0
              ,(SELECT trc1.xtrsrc_id
                      ,trc1.assoc_xtrsrc_id
                      ,SQRT( (x1.ra - rc1.wm_ra) * COS(RADIANS(x1.decl))
                            *(x1.ra - rc1.wm_ra) * COS(RADIANS(x1.decl))
                            / (x1.ra_err * x1.ra_err +
                               rc1.wm_ra_err * rc1.wm_ra_err)
                           + (x1.decl - rc1.wm_decl) * (x1.decl - rc1.wm_decl)
                             / (x1.decl_err * x1.decl_err + rc1.wm_decl_err *
                                rc1.wm_decl_err)
                           ) AS r1
                  FROM temprunningcatalog trc1
                      ,runningcatalog rc1
                      ,extractedsources x1
                 WHERE trc1.assoc_xtrsrc_id IN (SELECT assoc_xtrsrc_id
                                                 FROM temprunningcatalog
                                               GROUP BY assoc_xtrsrc_id
                                               HAVING COUNT(*) > 1
                                              )
                   AND trc1.xtrsrc_id = rc1.xtrsrc_id
                   AND trc1.assoc_xtrsrc_id = x1.xtrsrcid
               ) t1
         WHERE t1.assoc_xtrsrc_id = t0.assoc_xtrsrc_id
           AND t1.r1 > t0.min_r1
        """
        cursor.execute(query)
        results = zip(*cursor.fetchall())
        if len(results) != 0:
            xtrsrc_id = results[0]
            assoc_xtrsrc_id = results[1]
            # TODO: Consider setting row to inactive instead of deleting
            query = """\
            DELETE
              FROM temprunningcatalog
             WHERE xtrsrc_id = %s
               AND assoc_xtrsrc_id = %s
            """
            for j in range(len(xtrsrc_id)):
                cursor.execute(query, (xtrsrc_id[j], assoc_xtrsrc_id[j]))
                if not AUTOCOMMIT:
                    conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _insert_multiple_assocs(conn):
    """Insert sources with multiple associations

    -2- Now, we take care of the sources in the running catalogue that
    have more than one counterpart among the extracted sources.

    We now make two entries in the running catalogue, in stead of the
    one we had before. Therefore, we 'swap' the ids.
    """

    try:
        cursor = conn.cursor()
        query = """\
        INSERT INTO assocxtrsources
          (xtrsrc_id
          ,assoc_xtrsrc_id
          ,assoc_distance_arcsec
          ,assoc_r
          ,assoc_lr_method
          )
          SELECT t.assoc_xtrsrc_id
                ,t.xtrsrc_id
                ,3600 * DEGREES(2 * ASIN(SQRT((r.x - x.x) * (r.x - x.x)
                                          + (r.y - x.y) * (r.y - x.y)
                                          + (r.z - x.z) * (r.z - x.z)
                                          ) / 2) ) AS assoc_distance_arcsec
                ,3600 * sqrt(
                    ( (r.wm_ra * cos(RADIANS(r.wm_decl)) - x.ra * cos(RADIANS(x.decl)))
                     *(r.wm_ra * cos(RADIANS(r.wm_decl)) - x.ra * cos(RADIANS(x.decl)))
                    ) 
                    / (r.wm_ra_err * r.wm_ra_err + x.ra_err * x.ra_err)
                    + ((r.wm_decl - x.decl) * (r.wm_decl - x.decl)) 
                    / (r.wm_decl_err * r.wm_decl_err + x.decl_err * x.decl_err)
                            ) as assoc_r
                ,1
            FROM temprunningcatalog t
                ,runningcatalog r
                ,extractedsources x
           WHERE t.xtrsrc_id = r.xtrsrc_id
             AND t.xtrsrc_id = x.xtrsrcid
             AND t.xtrsrc_id IN (SELECT xtrsrc_id
                                   FROM temprunningcatalog
                                 GROUP BY xtrsrc_id
                                 HAVING COUNT(*) > 1
                                )
        """
        cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _insert_first_of_assocs(conn):
    """Insert identical ids

    -3- And, we have to insert identical ids to identify a light-curve
    starting point.
    """

    try:
        cursor = conn.cursor()
        query = """\
        INSERT INTO assocxtrsources
          (xtrsrc_id
          ,assoc_xtrsrc_id
          ,assoc_distance_arcsec
          ,assoc_r
          ,assoc_lr_method
          )
          SELECT assoc_xtrsrc_id
                ,assoc_xtrsrc_id
                ,0
                ,0
                ,2
            FROM temprunningcatalog
           WHERE xtrsrc_id IN (SELECT xtrsrc_id
                                 FROM temprunningcatalog
                               GROUP BY xtrsrc_id
                               HAVING COUNT(*) > 1
                              )
        """
        cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _flag_swapped_assocs(conn):
    """Throw away swapped ids

    -4- And, we throw away the swapped id.

    It might be better to flag this record: consider setting rows to
    inactive instead of deleting
    """
    try:
        cursor = conn.cursor()
        query = """\
        DELETE
          FROM assocxtrsources
         WHERE xtrsrc_id IN (SELECT xtrsrc_id
                               FROM temprunningcatalog
                             GROUP BY xtrsrc_id
                             HAVING COUNT(*) > 1
                            )
        """
        cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _insert_multiple_assocs_runcat(conn):
    """Insert new ids of the sources in the running catalogue"""

    try:
        cursor = conn.cursor()
        query = """\
        INSERT INTO runningcatalog
          (xtrsrc_id
          ,ds_id
          ,band
          ,datapoints
          ,zone
          ,wm_ra
          ,wm_decl
          ,wm_ra_err
          ,wm_decl_err
          ,avg_wra
          ,avg_wdecl
          ,avg_weight_ra
          ,avg_weight_decl
          ,x
          ,y
          ,z
          ,avg_I_peak
          ,avg_I_peak_sq
          ,avg_weight_peak
          ,avg_weighted_I_peak
          ,avg_weighted_I_peak_sq
          )
          SELECT assoc_xtrsrc_id
                ,ds_id
                ,band
                ,datapoints
                ,zone
                ,wm_ra
                ,wm_decl
                ,wm_ra_err
                ,wm_decl_err
                ,avg_wra
                ,avg_wdecl
                ,avg_weight_ra
                ,avg_weight_decl
                ,x
                ,y
                ,z
                ,avg_I_peak
                ,avg_I_peak_sq
                ,avg_weight_peak
                ,avg_weighted_I_peak
                ,avg_weighted_I_peak_sq
            FROM temprunningcatalog
           WHERE xtrsrc_id IN (SELECT xtrsrc_id
                                 FROM temprunningcatalog
                               GROUP BY xtrsrc_id
                               HAVING COUNT(*) > 1
                              )
        """
        cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _flag_old_assocs_runcat(conn):
    """Here the old assocs in runcat will be deleted."""

    # TODO: Consider setting row to inactive instead of deleting
    try:
        cursor = conn.cursor()
        query = """\
        DELETE
          FROM runningcatalog
         WHERE xtrsrc_id IN (SELECT xtrsrc_id
                               FROM temprunningcatalog
                             GROUP BY xtrsrc_id
                             HAVING COUNT(*) > 1
                            )
        """
        cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _flag_multiple_assocs(conn):
    """Delete the multiple assocs from the temporary running catalogue table"""

    try:
        cursor = conn.cursor()
        query = """\
        DELETE
          FROM temprunningcatalog
         WHERE xtrsrc_id IN (SELECT xtrsrc_id
                               FROM temprunningcatalog
                             GROUP BY xtrsrc_id
                             HAVING COUNT(*) > 1
                            )
        """
        cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _insert_single_assocs(conn):
    """Insert remaining 1-1 associations into assocxtrsources table"""
    #TODO: check whether last row (t.xtrsrc_id = x.xtrsrcid) should be
    #      t.assocxtrsrc_id = ...)
    try:
        cursor = conn.cursor()
        query = """\
        INSERT INTO assocxtrsources
          (xtrsrc_id
          ,assoc_xtrsrc_id
          ,assoc_distance_arcsec
          ,assoc_r
          ,assoc_lr_method
          )
          SELECT t.xtrsrc_id
                ,t.assoc_xtrsrc_id
                ,3600 * DEGREES(2 * ASIN(SQRT((r.x - x.x) * (r.x - x.x)
                                          + (r.y - x.y) * (r.y - x.y)
                                          + (r.z - x.z) * (r.z - x.z)
                                          ) / 2) ) AS assoc_distance_arcsec
                ,3600 * sqrt(
                    ((r.wm_ra * cos(RADIANS(r.wm_decl)) 
                     - x.ra * cos(RADIANS(x.decl))) 
                    * (r.wm_ra * cos(RADIANS(r.wm_decl)) 
                     - x.ra * cos(RADIANS(x.decl)))) 
                    / (r.wm_ra_err * r.wm_ra_err + x.ra_err*x.ra_err)
                    +
                    ((r.wm_decl - x.decl) * (r.wm_decl - x.decl)) 
                    / (r.wm_decl_err * r.wm_decl_err + x.decl_err*x.decl_err)
                            ) as assoc_r
                ,3
            FROM temprunningcatalog t
                ,runningcatalog r
                ,extractedsources x
           WHERE t.xtrsrc_id = r.xtrsrc_id
             AND t.xtrsrc_id = x.xtrsrcid
        """
        cursor.execute(query)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _update_runningcatalog(conn):
    """Update the running catalog"""

    try:
        cursor = conn.cursor()
        query = """\
SELECT datapoints
      ,zone
      ,wm_ra
      ,wm_decl
      ,wm_ra_err
      ,wm_decl_err
      ,avg_wra
      ,avg_wdecl
      ,avg_weight_ra
      ,avg_weight_decl
      ,x
      ,y
      ,z
      ,avg_I_peak
      ,avg_I_peak_sq
      ,avg_weight_peak
      ,avg_weighted_I_peak
      ,avg_weighted_I_peak_sq
      ,xtrsrc_id
  FROM temprunningcatalog
        """
        cursor.execute(query)
        results = cursor.fetchall()
        query = """\
UPDATE runningcatalog
  SET datapoints = %s
     ,zone = %s
     ,wm_ra = %s
     ,wm_decl = %s
     ,wm_ra_err = %s
     ,wm_decl_err = %s
     ,avg_wra = %s
     ,avg_wdecl = %s
     ,avg_weight_ra = %s
     ,avg_weight_decl = %s
     ,x = %s
     ,y = %s
     ,z = %s
     ,avg_I_peak = %s
     ,avg_I_peak_sq = %s
     ,avg_weight_peak = %s
     ,avg_weighted_I_peak = %s
     ,avg_weighted_I_peak_sq = %s
WHERE xtrsrc_id = %s
"""
        for result in results:
            cursor.execute(query, tuple(result))
            if not AUTOCOMMIT:
                conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _count_known_sources(conn, image_id, deRuiter_r):
    """Count number of extracted sources that are known in the running
    catalog"""

    cursor = conn.cursor()
    try:
        query = """\
        SELECT COUNT(*)
          FROM extractedsources x0
              ,images im0
              ,runningcatalog b0
         WHERE x0.image_id = %s
           AND x0.image_id = im0.imageid
           AND im0.ds_id = b0.ds_id
           AND b0.zone BETWEEN x0.zone - cast(0.025 as integer)
                           AND x0.zone + cast(0.025 as integer)
           AND b0.wm_decl BETWEEN x0.decl - 0.025
                              AND x0.decl + 0.025
           AND b0.wm_ra BETWEEN x0.ra - alpha(0.025,x0.decl)
                            AND x0.ra + alpha(0.025,x0.decl)
           AND SQRT(  (x0.ra * COS(RADIANS(x0.decl)) - b0.wm_ra * COS(RADIANS(b0.wm_decl)))
                    * (x0.ra * COS(RADIANS(x0.decl)) - b0.wm_ra * COS(RADIANS(b0.wm_decl)))
                    / (x0.ra_err * x0.ra_err + b0.wm_ra_err * b0.wm_ra_err)
                   + (x0.decl - b0.wm_decl) * (x0.decl - b0.wm_decl)
                    / (x0.decl_err * x0.decl_err + b0.wm_decl_err * b0.wm_decl_err)
                   ) < %s
        """
        cursor.execute(query, (image_id, deRuiter_r/3600.))
        y = cursor.fetchall()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _insert_new_assocs(conn, image_id, deRuiter_r):
    """Insert new associations for unknown sources

    This inserts new associations for the sources that were not known
    in the running catalogue (i.e. they did not have an entry in the
    runningcatalog table).
    """

    cursor = conn.cursor()
    try:
        query = """\
        INSERT INTO assocxtrsources
          (xtrsrc_id
          ,assoc_xtrsrc_id
          ,assoc_distance_arcsec
          ,assoc_r
          ,assoc_lr_method
          )
          SELECT x1.xtrsrcid as xtrsrc_id
                ,x1.xtrsrcid as assoc_xtrsrc_id
                ,0
                ,0
                ,4
            FROM extractedsources x1
           WHERE x1.image_id = %s
             AND x1.xtrsrcid NOT IN (
                 SELECT x0.xtrsrcid
                  FROM extractedsources x0
                      ,runningcatalog b0
                      ,images im0
                 WHERE x0.image_id = %s
                   AND x0.image_id = im0.imageid
                   AND im0.ds_id = b0.ds_id
                   AND b0.zone BETWEEN x0.zone - cast(0.025 as integer)
                                   AND x0.zone + cast(0.025 as integer)
                   AND b0.wm_decl BETWEEN x0.decl - 0.025
                                            AND x0.decl + 0.025
                   AND b0.wm_ra BETWEEN x0.ra - alpha(0.025,x0.decl)
                                          AND x0.ra + alpha(0.025,x0.decl)
                   AND SQRT(  (x0.ra * COS(RADIANS(x0.decl)) - b0.wm_ra * COS(RADIANS(b0.wm_decl)))
                            * (x0.ra * COS(RADIANS(x0.decl)) - b0.wm_ra * COS(RADIANS(b0.wm_decl)))
                            / (x0.ra_err * x0.ra_err + b0.wm_ra_err * b0.wm_ra_err)
                           + (x0.decl - b0.wm_decl) * (x0.decl - b0.wm_decl)
                            / (x0.decl_err * x0.decl_err + b0.wm_decl_err * b0.wm_decl_err)
                           ) < %s
                                    )
        """
        cursor.execute(query, (image_id, image_id, deRuiter_r/3600.))
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _insert_new_source_runcat(conn, image_id, deRuiter_r):
    """Insert new sources into the running catalog"""
    # TODO: check zone cast in search radius!
    try:
        cursor = conn.cursor()
        query = """\
        INSERT INTO runningcatalog
          (xtrsrc_id
          ,ds_id
          ,band
          ,datapoints
          ,zone
          ,wm_ra
          ,wm_decl
          ,wm_ra_err
          ,wm_decl_err
          ,avg_wra
          ,avg_wdecl
          ,avg_weight_ra
          ,avg_weight_decl
          ,x
          ,y
          ,z
          ,avg_I_peak
          ,avg_I_peak_sq
          ,avg_weight_peak
          ,avg_weighted_I_peak
          ,avg_weighted_I_peak_sq
          )
          SELECT x1.xtrsrcid
                ,im1.ds_id
                ,band
                ,1
                ,x1.zone
                ,x1.ra
                ,x1.decl
                ,x1.ra_err
                ,x1.decl_err
                ,x1.ra / (x1.ra_err * x1.ra_err)
                ,x1.decl / (x1.decl_err * x1.decl_err)
                ,1 / (x1.ra_err * x1.ra_err)
                ,1 / (x1.decl_err * x1.decl_err)
                ,x1.x
                ,x1.y
                ,x1.z
                ,I_peak
                ,I_peak * I_peak
                ,1 / (I_peak_err * I_peak_err)
                ,I_peak / (I_peak_err * I_peak_err)
                ,I_peak * I_peak / (I_peak_err * I_peak_err)
            FROM extractedsources x1
                ,images im1
           WHERE x1.image_id = %s
             AND x1.image_id = im1.imageid
             AND x1.xtrsrcid NOT IN (
                 SELECT x0.xtrsrcid
                  FROM extractedsources x0
                      ,runningcatalog b0
                      ,images im0
                 WHERE x0.image_id = %s
                   AND x0.image_id = im0.imageid
                   AND im0.ds_id = b0.ds_id
                   AND b0.zone BETWEEN CAST(FLOOR(x0.zone - 0.025) AS INTEGER)
                                   AND CAST(FLOOR(x0.zone + 0.025) AS INTEGER)
                   AND b0.wm_decl BETWEEN x0.decl - 0.025
                                      AND x0.decl + 0.025
                   AND b0.wm_ra BETWEEN x0.ra - alpha(0.025,x0.decl)
                                    AND x0.ra + alpha(0.025,x0.decl)
                   AND SQRT(  (x0.ra * COS(RADIANS(x0.decl)) - b0.wm_ra * COS(RADIANS(b0.wm_decl)))
                            * (x0.ra * COS(RADIANS(x0.decl)) - b0.wm_ra * COS(RADIANS(b0.wm_decl)))
                            / (x0.ra_err * x0.ra_err + b0.wm_ra_err * b0.wm_ra_err)
                           + (x0.decl - b0.wm_decl) * (x0.decl - b0.wm_decl)
                            / (x0.decl_err * x0.decl_err + b0.wm_decl_err * b0.wm_decl_err)
                           ) < %s
                   )
        """
        cursor.execute(query, (image_id, image_id, deRuiter_r/3600.))
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s." % query)
        raise
    finally:
        cursor.close()


def _associate_across_frequencies(conn, ds_id, image_id, deRuiter_r=DERUITER_R):
    """Associate sources in running catalog across frequency bands

    The dimensionless distance between two sources is given by the
    "De Ruiter radius", see Ch2&3 of thesis Scheers.

    Here we use a default value of deRuiter_r = 3.717/3600. for a
    reliable association.
    """
    return
    try:
        cursor = conn.cursor()
        query = """\
        SELECT COUNT(*)
              /*r1.xtrsrc_id AS runcat_id
              ,r1.band AS band
              ,r2.xtrsrc_id AS assoc_runcat_id
              ,r2.band AS assoc_band*/
          FROM runningcatalog r1
              ,runningcatalog r2
              ,images im1
         WHERE r1.ds_id = %s
           AND im1.imageid = %s
           AND r1.band = im1.band
           AND r2.ds_id = r1.ds_id
           AND r2.band <> r1.band
           AND r2.zone BETWEEN CAST(FLOOR(r1.decl - 0.025) AS INTEGER)
                           AND CAST(FLOOR(r1.decl + 0.025) AS INTEGER)
           AND r2.decl BETWEEN r1.decl - 0.025
                           AND r1.decl + 0.025
           AND r2.ra BETWEEN r1.ra - alpha(0.025, r1.decl)
                         AND r1.ra + alpha(0.025, r1.decl)
           AND SQRT( ((r1.ra * COS(RADIANS(r1.decl)) - r2.ra * COS(RADIANS(r2.decl))) 
                      * (r1.ra * COS(RADIANS(r1.decl)) - r2.ra * COS(RADIANS(r2.decl))))
                     / (r1.ra_err * r1.ra_err + r2.ra_err * r2.ra_err)
                   + ((r1.decl - r2.decl) * (r1.decl - r2.decl))
                    / (r1.decl_err * r1.decl_err + r2.decl_err * r2.decl_err)
                   ) < %s
        """
        cursor.execute(query, (ds_id, image_id, deRuiter_r/3600.))
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Failed on query nr %s; for reason %s" % (query, e))
        raise
    finally:
        cursor.close()


def associate_extracted_sources(conn, image_id, deRuiter_r=DERUITER_R):
    """Associate extracted sources with sources detected in the running
    catalog

    The dimensionless distance between two sources is given by the
    "De Ruiter radius", see Ch2&3 of thesis Scheers.

    Here we use a default value of deRuiter_r = 3.717/3600. for a
    reliable association.
    """

    _empty_temprunningcatalog(conn)
    _insert_temprunningcatalog(conn, image_id, deRuiter_r)
    _flag_multiple_counterparts_in_runningcatalog(conn)
    _insert_multiple_assocs(conn)
    _insert_first_of_assocs(conn)
    _flag_swapped_assocs(conn)
    _insert_multiple_assocs_runcat(conn)
    _flag_old_assocs_runcat(conn)
    _flag_multiple_assocs(conn)
    #+-----------------------------------------------------+
    #| After all this, we are now left with the 1-1 assocs |
    #+-----------------------------------------------------+
    _insert_single_assocs(conn)
    _update_runningcatalog(conn)
    _empty_temprunningcatalog(conn)
    _count_known_sources(conn, image_id, deRuiter_r)
    _insert_new_assocs(conn, image_id, deRuiter_r)
    _insert_new_source_runcat(conn, image_id, deRuiter_r)
    #_associate_across_frequencies(conn, ds_id, image_id, deRuiter_r)


def select_single_epoch_detection(conn, dsid):
    """Select sources and variability indices in the running catalog"""

    results = []
    cursor = conn.cursor()
    try:
        query = """\
SELECT xtrsrc_id
      ,ds_id
      ,datapoints
      ,wm_ra
      ,wm_decl
      ,wm_ra_err
      ,wm_decl_err
      ,sqrt(datapoints*(avg_I_peak_sq - avg_I_peak*avg_I_peak) /
            (datapoints-1)) / avg_I_peak as V
      ,(datapoints/(datapoints-1)) *
       (avg_weighted_I_peak_sq -
        avg_weighted_I_peak * avg_weighted_I_peak / avg_weight_peak)
       as eta
  FROM runningcatalog
 WHERE ds_id = %s
   AND datapoints = 1
"""
        cursor.execute(query, (dsid, ))
        results = cursor.fetchall()
        results = [dict(srcid=x[0], npoints=x[2], v_nu=x[7], eta_nu=x[8])
                   for x in results]
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error:
        logging.warn("Failed on query %s", query)
        raise
    finally:
        cursor.close()
    return results


def lightcurve(conn, xtrsrcid):
    """Obtain a light curve for a specific extractedsource

    Args:

        xtrsrcid (int): the source identifier that corresponds to a
        point on the light curve. Note that the point does not have to
        be the start (first) point of the light curve.

    Returns:

        A list of 5-tuples, each tuple containing (in order):

            - observation start time as a datetime.datetime object
            
            - integration time (float)
            
            - peak flux (float)
            
            - peak flux error (float)
            
            - database ID of this particular source
    """

    cursor = conn.cursor()
    try:
        query = """\
SELECT im.taustart_ts, im.tau_time, ex.i_peak, ex.i_peak_err, ex.xtrsrcid
FROM extractedsources ex, assocxtrsources ax, images im
WHERE ax.xtrsrc_id in
    (SELECT xtrsrc_id FROM assocxtrsources WHERE assoc_xtrsrc_id = %s)
  AND ex.xtrsrcid = ax.assoc_xtrsrc_id
  AND ex.image_id = im.imageid
ORDER BY im.taustart_ts"""
        cursor.execute(query, (xtrsrcid,))
        results = cursor.fetchall()
    except db.Error:
        query = query % xtrsrcid
        logging.warn("Failed to obtain light curve")
        logging.warn("Query failed:\n%s", query)
        raise
    finally:
        cursor.close()
    return results


# This function is private to the module, and is only called by
# 
def _select_variability_indices(conn, dsid, V_lim, eta_lim):
    """Select sources and variability indices in the running catalog

    This comes relatively easily, since we have kept track of the
    average fluxes and the variance measures, and thus can quickly
    obtain any sources that exceed a constant flux by a certain amount.

    Args:

        dsid (int): dataset of interest

        V_lim ():

        eta_lim ():
    """

    # To do: explain V_lim and eta_lim
    
    results = []
    cursor = conn.cursor()
    try:
        query = """\
SELECT
     xtrsrc_id
    ,ds_id
    ,datapoints
    ,wm_ra
    ,wm_decl
    ,wm_ra_err
    ,wm_decl_err
    ,t1.V_inter / t1.avg_i_peak as V
    ,t1.eta_inter / t1.avg_weight_peak as eta
FROM
    (SELECT
          xtrsrc_id
         ,ds_id
         ,datapoints
         ,wm_ra
         ,wm_decl
         ,wm_ra_err
         ,wm_decl_err
         ,avg_i_peak
         ,avg_weight_peak
         ,CASE WHEN datapoints = 1
               THEN 0
               ELSE sqrt(cast(datapoints as double precision) * (avg_I_peak_sq - avg_I_peak*avg_I_peak) / (cast(datapoints as double precision) - 1.0))
               END
          AS V_inter
         ,CASE WHEN datapoints = 1
               THEN 0
               ELSE (cast(datapoints as double precision) / (cast(datapoints as double precision)-1.0)) * (avg_weight_peak*avg_weighted_I_peak_sq - avg_weighted_I_peak * avg_weighted_I_peak )
               END
          AS eta_inter
      FROM runningcatalog
      WHERE ds_id = %s
      ) t1
  WHERE t1.V_inter / t1.avg_i_peak > %s
    AND t1.eta_inter / t1.avg_weight_peak > %s
"""
        cursor.execute(query, (dsid, V_lim, eta_lim))
        results = cursor.fetchall()
        results = [dict(
            srcid=x[0], npoints=x[2], v_nu=x[7], eta_nu=x[8], dataset=x[1],
            ra=x[3], dec=x[4], ra_err=x[5], dec_err=x[6])
                   for x in results]
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error:
        query = query % (dsid, V_lim, eta_lim)
        logging.warn("Query failed:\n%s", query)
        raise
    finally:
        cursor.close()
    return results

        
def detect_variable_sources(conn, dsid, V_lim, eta_lim):
    """Detect variability in extracted sources compared to the previous
    detections"""

    return _select_variability_indices(conn, dsid, V_lim, eta_lim)


def _insert_cat_assocs(conn, image_id, radius, deRuiter_r):
    """Insert found xtrsrc--catsrc associations into assoccatsources table.

    The search for cataloged counterpart sources is done in the catalogedsources
    table, which should have been preloaded with a selection of 
    the catalogedsources, depending on the expected field of view.
    
    """
    
    try:
        cursor = conn.cursor()
        query = """\
        INSERT INTO assoccatsources
          (xtrsrc_id
          ,assoc_catsrc_id
          ,assoc_distance_arcsec
          ,assoc_lr_method
          ,assoc_r
          ,assoc_loglr
          )
          SELECT xtrsrcid AS xtrsrc_id
                ,catsrcid AS assoc_catsrc_id
                ,3600 * DEGREES(2 * ASIN(SQRT((x0.x - c0.x) * (x0.x - c0.x)
                                          + (x0.y - c0.y) * (x0.y - c0.y)
                                          + (x0.z - c0.z) * (x0.z - c0.z)
                                          ) / 2) ) AS assoc_distance_arcsec
                ,3
                ,3600 * sqrt( ((x0.ra * cos(RADIANS(x0.decl)) - c0.ra * cos(RADIANS(c0.decl))) 
                             * (x0.ra * cos(RADIANS(x0.decl)) - c0.ra * cos(RADIANS(c0.decl)))) 
                             / (x0.ra_err * x0.ra_err + c0.ra_err*c0.ra_err)
                            +
                              ((x0.decl - c0.decl) * (x0.decl - c0.decl)) 
                             / (x0.decl_err * x0.decl_err + c0.decl_err*c0.decl_err)
                            ) as assoc_r
                ,LOG10(EXP((   (x0.ra * COS(RADIANS(x0.decl)) - c0.ra * COS(RADIANS(c0.decl)))
                             * (x0.ra * COS(RADIANS(x0.decl)) - c0.ra * COS(RADIANS(x0.decl)))
                             / (x0.ra_err * x0.ra_err + c0.ra_err * c0.ra_err)
                            +  (x0.decl - c0.decl) * (x0.decl - c0.decl) 
                             / (x0.decl_err * x0.decl_err + c0.decl_err * c0.decl_err)
                           ) / 2
                          )
                      /
                      (2 * PI() * SQRT(x0.ra_err * x0.ra_err + c0.ra_err * c0.ra_err)
                                * SQRT(x0.decl_err * x0.decl_err + c0.decl_err * c0.decl_err) * %s)
                      ) AS assoc_loglr
            FROM (select xtrsrcid
                        ,ra
                        ,decl
                        ,ra_err
                        ,decl_err
                        ,cast(floor(decl - %s) as integer) as zone_min
                        ,cast(floor(decl + %s) as integer) as zone_max
                        ,ra + alpha(%s, decl) as ra_max
                        ,ra - alpha(%s, decl) as ra_min
                        ,decl - %s as decl_min
                        ,decl + %s as decl_max
                        ,x
                        ,y
                        ,z
                    from extractedsources
                   where image_id = %s
                 ) x0
                ,catalogedsources c0
           WHERE c0.zone BETWEEN zone_min AND zone_max
             AND c0.decl BETWEEN decl_min AND decl_max
             AND c0.ra BETWEEN ra_min AND ra_max
             and x0.x*c0.x + x0.y*c0.y + x0.z*c0.z > %s
             AND SQRT(  (x0.ra * COS(RADIANS(x0.decl)) - c0.ra * COS(RADIANS(c0.decl)))
                      * (x0.ra * COS(RADIANS(x0.decl)) - c0.ra * COS(RADIANS(c0.decl)))
                      / (x0.ra_err * x0.ra_err + c0.ra_err * c0.ra_err)
                     + (x0.decl - c0.decl) * (x0.decl - c0.decl)
                      / (x0.decl_err * x0.decl_err + c0.decl_err * c0.decl_err)
                     ) < %s
        """
        cursor.execute(query, (BG_DENSITY, radius, radius, radius, radius, radius, radius, 
                               image_id,math.cos(math.pi*radius/180.), deRuiter_r/3600.))
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Query failed: %s." % query)
        raise
    finally:
        cursor.close()


def associate_with_catalogedsources(conn, image_id, radius=0.025, deRuiter_r=DERUITER_R):
    """Associate extracted sources in specified image with known sources 
    in the external catalogues

    radius (typical 90arcsec=0.025deg), is the radius of the area centered
    at the extracted source which are searched for counterparts in the catalogues.
    
    The dimensionless distance between two sources is given by the
    "De Ruiter radius", see Ch2&3 of thesis Scheers.

    Here we use a default value of deRuiter_r = 3.717/3600. for a
    reliable association.

    Every found candidate is added to the assoccatsources table.
    """

    _insert_cat_assocs(conn, image_id, radius, deRuiter_r)


def associate_catalogued_sources_in_area(conn, ra, dec, radius, deRuiter_r=DERUITER_R/3600.):
    pass


# To do: move these two functions to unit tests
# Are these being used anyway? They appear to be defined, but not used
def concurrency_test_fixedalpha(conn):
    """Unit test function to test concurrency
    """

    theta = 0.025
    decl = 80.
    alpha = None
    try:
        cursor = conn.cursor()
        query = """\
        SELECT alpha(%s, %s)
        """
        cursor.execute(query, (theta, decl))
        alpha = cursor.fetchone()[0]
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        logging.warn("Query failed: %s." % query)
        raise
    finally:
        conn.cursor().close()
    return alpha


def concurrency_test_randomalpha(conn):
    """Unit test function to test concuurency
    """

    import random
    theta = 0.025
    decl = random.random() * 90
    alpha = None
    try:
        cursor = conn.cursor()
        query = """\
        SELECT alpha(%s, %s)
        """
        cursor.execute(query, (theta, decl))
        alpha = cursor.fetchone()[0]
    except db.Error, e:
        logging.warn("Query failed: %s." % query)
        raise
    finally:
        conn.cursor().close()
    return alpha


def columns_from_table(conn, table, keywords=None, where=None):
    """Obtain specific column (keywords) values from 'table', with
    kwargs limitations.

    A very simple helper function, that builds an SQL query to obtain
    the specified columns from 'table', and then executes that
    query. Optionally, the WHERE clause can be specified using the
    where dictionary. It returns a list of a
    dict (with the originally supplied keywords as dictionary keys),
    which can be empty.

    Example:
    
        >>> columns_from_table(conn, 'images',
            keywords=['taustart_ts', 'tau_time', 'freq_eff', 'freq_bw'], where={'imageid': 1})
            [{'freq_eff': 133984375.0, 'taustart_ts': datetime.datetime(2010, 10, 9, 9, 4, 2), 'tau_time': 14400.0, 'freq_bw': 1953125.0}]

        This builds the SQL query:
        "SELECT taustart_ts, tau_time, freq_eff, freq_bw FROM images WHERE imageid=1"

    This function is implemented mainly to abstract and hide the SQL
    functionality from the Python interface.

    Args:

        conn: database connection object

        table (string): database table name

    Kwargs:

        keywords (list): column names to select from the table. None indicates all ('*')

        where (dict): where clause for the query, specified as a set
            of 'key = value' comparisons. Comparisons are and-ed
            together. Obviously, only 'is equal' comparisons are
            possible.

    Returns:

        (list): list of dicts. Each dict contains the given keywords,
            or all if keywords=None. Each element of the list
            corresponds to a table row.
        
    """

    # Note from the Python docs: If items(), keys(), values(),
    # iteritems(), iterkeys(), and itervalues() are called with no
    # intervening modifications to the dictionary, the lists will
    # directly correspond.
    results = []
    if keywords is None:
        query = "SELECT * FROM " + table
    else:
        query = "SELECT " + ", ".join(keywords) + " FROM " + table
    if where is None:
        where = {}
    where_args = tuple(where.itervalues())
    where = " AND ".join(["%s=%%s" % key for key in where.iterkeys()])
    if where:
        query += " WHERE " + where
    try:
        cursor = conn.cursor()
        cursor.execute(query, where_args)
        results = cursor.fetchall()
        if keywords is None:
            keywords = [desc[0] for desc in cursor.description]
        results = [dict([(keyword, value) for keyword, value in zip(keywords, result)]) for result in results]
    except db.Error, exc:
        query = query % where_args
        logging.warn("Query failed: %s" % query)
        raise
    finally:
        conn.cursor().close()
    return results


def set_columns_for_table(conn, table, data=None, where=None):
    """Set specific columns (keywords) for 'table', with 'where'
    limitations.

    A simple helper function, that builds an SQL query to update the
    specified columns given by data for 'table', and then executes
    that query. Optionally, the WHERE clause can be specified using
    the 'where' dictionary.

    The data argument is a dictionary with the names and corresponding
    values of the columns that need to be updated.
    """

    # Note from the Python docs: If items(), keys(), values(),
    # iteritems(), iterkeys(), and itervalues() are called with no
    # intervening modifications to the dictionary, the lists will
    # directly correspond.
    query = "UPDATE " + table + " SET " + ", ".join(["%s=%%s" % key for key in data.iterkeys()])
    if where is None:
        where = {}
    where_args = tuple(where.itervalues())
    where = " AND ".join(["%s=%%s" % key for key in where.iterkeys()])
    values = tuple(data.itervalues())
    if where:
        query += " WHERE " + where
    try:
        cursor = conn.cursor()
        cursor.execute(query, values + where_args)
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error, e:
        query = query % (values + where_args)
        logging.warn("Query failed: %s", query)
        raise
    finally:
        cursor.close()


def get_imagefiles_for_ids(conn, image_ids):
    """Return a list of image filenames for the give image ids

    The actual returned list contains 2-tuples of (id, url)
    """
    
    where_string = ", ".join(["%s"] * len(image_ids))
    where_tuple = tuple(image_ids)
    query = ("""SELECT imageid, url FROM images WHERE imageid in (%s)""" % 
             where_string)
    cursor = conn.cursor()
    try:
        querytxt = query % where_tuple
        cursor.execute(query, where_tuple)
        results = cursor.fetchall()
        ## extra
        #if not AUTOCOMMIT:
        #    conn.commit()
    except db.Error, e:
        query = query % where_tuple
        logging.warn("Query failed: %s", query)
        raise
    finally:
        cursor.close()
    return results


def match_nearests_in_catalogs(conn, srcid, radius=1.0,
                              catalogid=None, assoc_r=DERUITER_R/3600.):
    """Match a source with position ra, decl with catalogedsources
    within radius

    The function does not return the best match, but a list of sources
    that are contained within radius, ordered by distance.

    One can limit the list of matches using assoc_r for a
    goodness-of-match measure.
    
    Args:

        srcid: xtrsrc_id in runningcatalog

    Kwargs:
    
        radius (float): search radius around the source to search, in
        degrees

        catalogid (int or list of ints): the catalog(s) to search. If
        none, all catalogs are searched for. A single integer
        specifies one catalog, while a list of integers specifies
        multiple catalogs.

        assoc_r (float): dimensionless search radius, in units of the
        De Ruiter radius. 3.7/3600. is a good value, though the
        default is 180 (which will match all sources). Assoc_r sets a
        cut off for the found sources.
        
    The return values are ordered first by catalog, then by
    assoc_r. So the first source in the list is the closest match for
    a catalog.
    """
    zoneheight = 1.0
    catalog_filter = ""
    if catalogid is None:
        catalog_filter = ""
    else:
        try:
            iter(catalogid)
            # Note: cast to int, to ensure proper type
            catalog_filter = (
                "c.catid in (%s) AND " % ", ".join(
                [str(int(catid)) for catid in catalogid]))
        except TypeError:
            catalog_filter = "c.catid = %d AND " % catalogid
    
    subquery = """\
SELECT
    cs.catsrcid
   ,c.catid
   ,c.catname
   ,cs.catsrcname
   ,cs.ra
   ,cs.decl
   ,cs.ra_err
   ,cs.decl_err
   ,3600 * DEGREES(2 * ASIN(SQRT(
       (rc.x - cs.x) * (rc.x - cs.x)
       + (rc.y - cs.y) * (rc.y - cs.y)
       + (rc.z - cs.z) * (rc.z - cs.z)
       ) / 2)
   ) AS assoc_distance_arcsec
   ,SQRT( (rc.wm_ra - cs.ra) * COS(RADIANS(rc.wm_decl)) * (rc.wm_ra - cs.ra) * COS(RADIANS(rc.wm_decl))
   / (cast(rc.wm_ra_err as double precision) * rc.wm_ra_err + cs.ra_err * cs.ra_err)
   + (rc.wm_decl - cs.decl) * (rc.wm_decl - cs.decl)
   / (cast(rc.wm_decl_err as double precision) * rc.wm_decl_err + cs.decl_err * cs.decl_err)
   ) AS assoc_r
FROM (
     SELECT
     wm_ra - alpha(%%s, wm_decl) as ra_min
    ,wm_ra + alpha(%%s, wm_decl) as ra_max
    ,CAST(FLOOR((wm_decl - %%s) / %%s) AS INTEGER) as zone_min
    ,CAST(FLOOR((wm_decl + %%s) / %%s) AS INTEGER) as zone_max
    ,wm_decl - %%s as decl_min
    ,wm_decl + %%s as decl_max
    ,x
    ,y
    ,z
    ,wm_ra
    ,wm_decl
    ,wm_ra_err
    ,wm_decl_err
    FROM runningcatalog
    WHERE xtrsrc_id = %%s
    ) rc
    ,catalogedsources cs
    ,catalogs c
WHERE
      %(catalog_filter)s
  cs.cat_id = c.catid
  AND cs.zone BETWEEN rc.zone_min AND rc.zone_max
  AND cs.ra BETWEEN rc.ra_min and rc.ra_max
  AND cs.decl BETWEEN rc.decl_min and rc.decl_max
  AND cs.x * rc.x + cs.y * rc.y + cs.z * rc.z > COS(RADIANS(%%s))
""" % {'catalog_filter': catalog_filter}
#  AND cs.ra BETWEEN rc.wm_ra - alpha(%%s, rc.wm_decl)
#                AND rc.wm_ra + alpha(%%s, rc.wm_decl)
    query = """\
SELECT 
    t.catsrcid
   ,t.catsrcname
   ,t.catid
   ,t.catname
   ,t.ra
   ,t.decl
   ,t.ra_err
   ,t.decl_err
   ,t.assoc_distance_arcsec
   ,t.assoc_r
FROM (%(subquery)s) as t
WHERE t.assoc_r < %%s
ORDER BY t.catid ASC, t.assoc_r ASC
""" % {'subquery': subquery}
    results = []
    try:
        cursor = conn.cursor()
        cursor.execute(query,  (radius, radius, radius, zoneheight,
                                radius, zoneheight, radius, radius,
                                srcid, radius, assoc_r))
        results = cursor.fetchall()
        results = [
            {'catsrcid': result[0], 'catsrcname': result[1],
             'catid': result[2], 'catname': result[3],
             'ra': result[4], 'decl': result[5],
             'ra_err': result[6], 'decl_err': result[7],
             'dist_arcsec': result[8], 'assoc_r': result[9]}
            for result in results]
    except db.Error, e:
        query = query % (radius, radius, radius, zoneheight,
                         radius, zoneheight,
                         radius, radius, srcid, radius, assoc_r)
        logging.warn("Query failed: %s", query)
        raise
    finally:
        cursor.close()
    return results


def monitoringlist_not_observed(conn, image_id):
    """Return a list of sources from the monitoringlist that have no
    association with the extracted sources for this image

    We do this by matching the monitoring list xtrsrc_ids with the
    extractedsources xtrsrcids through the assocxtrsources. Using a
    left outer join, we get nulls in the place where a source should
    have been, but isn't: these are the sources that are not in
    extractedosurces and thus weren't automatically picked up by the
    sourcefinder. We limit our query using the image_id (and ds_id
    through images.ds_id).

    Lastly, we get the best (weighted averaged) position for the
    sources to be monitored from the runningcatalog, which shows up in
    the final inner join.

    Args:

        conn: A database connection object.

        image_id (int): the image under consideration.

    Returns (list):

        A list of sources yet to be observed; each list item is a
        tuple with the ra, dec, xtrsrcid and monitorid of the source.
    """

    cursor = conn.cursor()
    query = """\
SELECT rc.wm_ra
      ,rc.wm_decl
      ,t2.xtrsrc_id2
      ,t2.monitorid
FROM
   (SELECT ml.monitorid AS monitorid
          ,ml.xtrsrc_id AS xtrsrc_id2
          ,t1.xtrsrc_id AS xtrsrc_id
          ,t1.assoc_xtrsrc_id AS assoc_xtrsrc_id
          ,t1.image_id AS image_id
          ,ml.ds_id AS ds_id
      FROM monitoringlist ml
      LEFT OUTER JOIN 
          (SELECT ax.xtrsrc_id as xtrsrc_id
                ,ex.xtrsrcid as xtrsrcid
                ,ex.image_id as image_id
                ,ax.assoc_xtrsrc_id as assoc_xtrsrc_id
            FROM extractedsources ex, assocxtrsources ax
            WHERE ex.xtrsrcid = ax.assoc_xtrsrc_id
            AND ex.image_id = %s
          ) t1
      ON ml.xtrsrc_id = t1.xtrsrc_id
      WHERE t1.assoc_xtrsrc_id IS NULL
    ) t2, images im, runningcatalog rc
WHERE im.ds_id = t2.ds_id
AND im.imageid = %s
AND rc.xtrsrc_id = t2.xtrsrc_id2
"""
    try:
        cursor.execute(query, (image_id, image_id))
        results = cursor.fetchall()
    except db.Error, e:
        query = query % (image_id, image_id)
        logging.warn("Query failed: %s", query)
        raise
    finally:
        cursor.close()
    return results

    
def is_monitored(conn, srcid):
    """Return whether a source is in the monitoring list"""

    cursor = conn.cursor()
    try:
        query = """\
SELECT COUNT(*) FROM monitoringlist WHERE xtrsrc_id = %s"""
        cursor.execute(query, (srcid,))
        result = bool(cursor.fetchone()[0])
    except db.Error, e:
        query = query % srcid
        logging.warn("Query failed: %s", query)
        raise
    finally:
        cursor.close()
    return result


def insert_monitoring_sources(conn, results, image_id):
    """Insert the list of measured monitoring sources for this image into
    extractedsources and runningcatalog.

    For user-inserted sources (i.e., sources that were not discovered
    automatically), the source will be inserted into the
    runningcatalog as well; for "normal" monitoring sources (i.e.,
    ones that preset a transient), this does not happen, to not
    pollute the runningcatalog averages for this entry.

    The insertion into runningcatalog can be done by xtrsrc_id from
    monitoringlist. In case it is negative, it is appended to
    runningcatalog, and xtrsrc_id is updated in the monitoringlist.
    """

    cursor = conn.cursor()
    # step through all the indiviudal results (/sources)
    for xtrsrc_id, monitorid, result in results:
        ra, dec, ra_err, dec_err, peak, peak_err, flux, flux_err, sigma, \
            semimajor, semiminor, pa = result
        x = math.cos(math.radians(dec)) * math.cos(math.radians(ra))
        y = math.cos(math.radians(dec)) * math.sin(math.radians(ra))
        z = math.sin(math.radians(dec))
        # Always insert them into extractedsources
        query = """\
        INSERT INTO extractedsources
          (image_id
          ,zone
          ,ra
          ,decl
          ,ra_err
          ,decl_err
          ,x
          ,y
          ,z
          ,det_sigma
          ,I_peak
          ,I_peak_err
          ,I_int
          ,I_int_err
          ,semimajor
          ,semiminor
          ,pa
          )
          VALUES
          (%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          ,%s
          )
"""
        try:
            cursor.execute(
                query, (image_id, int(math.floor(dec)), ra, dec, ra_err, dec_err,
                        x, y, z, sigma, peak, peak_err, flux, flux_err,
                        semimajor, semiminor, pa))
            if not AUTOCOMMIT:
                conn.commit()
            xtrsrcid = cursor.lastrowid
        except db.Error, e:
            query = query % (
                image_id, int(math.floor(dec)), ra, dec, ra_err, dec_err,
                x, y, z, sigma, peak, peak_err, flux, flux_err,
                semimajor, semiminor, pa)
            logging.warn("Query failed: %s", query)
            cursor.close()
            raise
        if xtrsrc_id < 0:
            # Insert as new source into the running catalog
            # and update the monitoringlist.xtrsrc_id
            query = """\
INSERT INTO runningcatalog
    (xtrsrc_id
    ,ds_id
    ,band
    ,datapoints
    ,zone
    ,wm_ra
    ,wm_decl
    ,wm_ra_err
    ,wm_decl_err
    ,avg_wra
    ,avg_wdecl
    ,avg_weight_ra
    ,avg_weight_decl
    ,x
    ,y
    ,z
    ,avg_I_peak
    ,avg_I_peak_sq
    ,avg_weight_peak
    ,avg_weighted_I_peak
    ,avg_weighted_I_peak_sq
    )
    SELECT
        t0.xtrsrcid
        ,im.ds_id
        ,im.band
        ,1
        ,t0.zone
        ,t0.ra
        ,t0.decl
        ,t0.ra_err
        ,t0.decl_err
        ,t0.ra
        ,t0.decl
        ,t0.ra_err
        ,t0.decl_err
        ,t0.x
        ,t0.y
        ,t0.z
        ,t0.flux
        ,t0.flux_sq
        ,t0.flux
        ,t0.flux
        ,t0.flux_sq
    FROM (SELECT
        ex.image_id
        ,ex.xtrsrcid
        ,ex.zone
        ,ex.ra
        ,ex.decl
        ,ex.ra_err
        ,ex.decl_err
        ,ex.x
        ,ex.y
        ,ex.z 
        ,ex.i_peak as flux
        ,ex.i_peak * ex.i_peak as flux_sq
        FROM extractedsources ex
        WHERE ex.xtrsrcid = %s
        ) as t0, images im
    WHERE im.imageid = %s
"""
            try:
                cursor.execute(query, (xtrsrcid, image_id))
                if not AUTOCOMMIT:
                    conn.commit()
            except db.Error, e:
                query = query % (image_id, xtrsrcid)
                logging.warn("query failed: %s", query)
                cursor.close()
                raise
            # Add it to the association table as well, so we can
            # obtain the lightcurve
            query = """\
INSERT INTO assocxtrsources
  (
  xtrsrc_id,
  assoc_xtrsrc_id,
  assoc_weight,
  assoc_distance_arcsec,
  assoc_lr_method,
  assoc_r, assoc_lr
  )
VALUES
  (%s, %s, 0, 0, 0, 0, 0)"""
            try:
                cursor.execute(query, (xtrsrcid, xtrsrcid))
                if not AUTOCOMMIT:
                    conn.commit()
            except db.Error, e:
                query = query % (xtrsrcid, xtrsrcid)
                logging.warn("query failed: %s", query)
                cursor.close()
                raise
            # Now update the monitoringlist.xtrsrc_id (note: the
            # original, possibly negative, xtrsrc_id is still held
            # safely in memory)
            query = """\
UPDATE monitoringlist SET xtrsrc_id=%s, image_id=%s WHERE monitorid=%s"""
            try:
                cursor.execute(query, (xtrsrcid, image_id, monitorid))
                if not AUTOCOMMIT:
                    conn.commit()
            except db.Error, e:
                query = query % (xtrsrcid, xtrsrc_id)
                logging.warn("query failed: %s", query)
                cursor.close()
                raise                    
        else:
            # We don't update the runningcatalog, because:
            # - the fluxes are below the detection limit, and
            #   add little to nothing to the average flux
            # - the positions will have large errors, and
            #   contribute very litte to the average position
            # We thus only need to update the association table,
            # and the image_id in the monitoringlist
            # the xtrsrc_id from the monitoringlist already
            # points to the original/first point
            query = """\
INSERT INTO assocxtrsources (xtrsrc_id, assoc_xtrsrc_id, assoc_weight, assoc_distance_arcsec, assoc_lr_method, assoc_r, assoc_lr)
VALUES (%s, %s, 0, 0, 0, 0, 0)"""
            try:
                cursor.execute(query, (xtrsrc_id, xtrsrcid))
                if not AUTOCOMMIT:
                    conn.commit()
            except db.Error, e:
                query = query % (xtrsrc_id, xtrsrcid)
                logging.warn("query failed: %s", query)
                cursor.close()
                raise
    cursor.close()
    

def insert_transient(conn, transient, dataset_id, images=None):
    """Insert a transient source in the database.
    Transients are stored in the transients table, as well as in
    the monitoring list.

    A check is performed where the base id (asocxtrsources.xtrsrc_id)
    for the light curve of the transient is queried, by assuming the
    current srcid falls within a light curve
    (assocxtrsources.assoc_xtrsrc_id = srcid). If this id already in the
    table, we replace that transient by this one.

    The reason we check the assocxtrsources, is that when there is a
    double source match, the main source id (as stored in the
    runningcatalog) may change; this results in transients already
    stored having a different id than the current transient, while
    they are in the fact the same transient. The xtrsrc_id of the
    stored id, however, should still be in the light curve of the new
    xtrsrc_id, as an assoc_xtrsrc_id. We thus update the transient,
    and replace the current transients.xtrsrc_id by the new srcid
    (=assocxtrsources.xtrsrc_id)

    We store the transient in the monitoring list to ensure its flux
    will be measured even when the transient drops below the detection
    threshold.
    """

    srcid = transient.srcid
    cursor = conn.cursor()
    try:  # Find the possible transient associated with the current source
        query = """\
SELECT transientid FROM transients WHERE xtrsrc_id IN (
SELECT assoc_xtrsrc_id FROM assocxtrsources WHERE xtrsrc_id = %s
)
"""
        cursor.execute(query, (srcid,))
        transientid = cursor.fetchone()
        if transientid:  # update/replace existing source
            query = """\
UPDATE transients SET
    xtrsrc_id = %s
    ,eta = %s
    ,V = %s
WHERE transientid = %s
"""
            cursor.execute(query, (srcid, transientid[0],
                                   transient.eta, transient.V))
        else:  # insert new source
            # First, let'find the current xtrsrc_id that belongs to the
            # current image: this is the trigger source id
            if images is None:
                image_set = ""
            else:
                image_set = ", ".join([str(image) for image in images])
            query = """\
SELECT ex.xtrsrcid FROM extractedsources ex, assocxtrsources ax
WHERE ex.image_id IN (%s) AND ex.xtrsrcid = ax.assoc_xtrsrc_id AND
ax.xtrsrc_id = %%s""" % image_set
            cursor.execute(query, (srcid,))
            trigger_srcid = cursor.fetchone()[0]
            query = """\
INSERT INTO transients (xtrsrc_id, eta, V, trigger_xtrsrc_id)
VALUES (%s, %s, %s, %s)
"""
            cursor.execute(query, (srcid, transient.eta, transient.V,
                                   trigger_srcid))
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error:
        logging.warn("Query %s failed", query)
        logging.debug("Query %s failed", query)
        cursor.close()
        raise
    try:
        query = """\
INSERT INTO monitoringlist
(xtrsrc_id, ra, decl, ds_id)
SELECT ex.xtrsrcid, 0, 0, %s
FROM extractedsources ex
WHERE ex.xtrsrcid = %s
  AND
    ex.xtrsrcid NOT IN
    (SELECT xtrsrc_id FROM monitoringlist)
"""
        cursor.execute(query, (dataset_id, srcid))
        if not AUTOCOMMIT:
            conn.commit()
    except db.Error:
        query = query % srcid
        logging.warn("Query %s failed", query)
        cursor.close()
        raise
    cursor.close()
