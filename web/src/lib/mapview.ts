/**
 * Map view state: flat projection with pan/zoom, or a rotatable orthographic globe.
 *
 * Both modes share d3-geo's projection API, so the choropleth, great-circle arcs, hatch
 * pattern and palette all work unchanged -- the only thing that swaps is the projection.
 * That is why a d3 globe was chosen over a WebGL one: `globe.gl`/three.js would look
 * glossier but needs a second rendering path and ~600KB, and none of the existing
 * choropleth/legend/accessibility work would transfer.
 *
 * The globe also removes a real geometric wart rather than just looking nicer: on a sphere
 * a great circle from Japan to the US crosses the Pacific naturally, with no antimeridian
 * clipping to reason about.
 */

import { geoEqualEarth, geoOrthographic, type GeoProjection } from 'd3-geo'

export type ViewMode = 'flat' | 'globe'

export interface ViewState {
  mode: ViewMode
  /** Flat mode: pan/zoom transform applied to the map group. */
  k: number
  x: number
  y: number
  /** Globe mode: [longitude, latitude] rotation, degrees. */
  lambda: number
  phi: number
}

export const INITIAL_VIEW: ViewState = {
  mode: 'flat',
  k: 1,
  x: 0,
  y: 0,
  // Opens on the Atlantic so the Americas and Europe -- the densest part of the data -- are
  // both visible without rotating.
  lambda: -30,
  phi: 15,
}

export const MIN_ZOOM = 1
export const MAX_ZOOM = 12

export function clampZoom(k: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, k))
}

/** Latitude is clamped short of the poles; past ±90 the globe flips disorientingly. */
export function clampPhi(phi: number): number {
  return Math.max(-80, Math.min(80, phi))
}

/** Wrap longitude into (-180, 180] so repeated dragging does not accumulate huge values. */
export function wrapLambda(lambda: number): number {
  return ((((lambda + 180) % 360) + 360) % 360) - 180
}

/**
 * Bounding box used to fit the flat projection.
 *
 * Antarctica is excluded: it has no sovereign issuer, so including it wasted roughly a sixth
 * of the panel height on a band of "no data" hatch.
 */
const POPULATED_WORLD = {
  type: 'Polygon',
  coordinates: [
    [
      [-180, 84],
      [180, 84],
      [180, -58],
      [-180, -58],
      [-180, 84],
    ],
  ],
} as never

export function buildProjection(
  view: ViewState,
  width: number,
  height: number,
): GeoProjection {
  if (view.mode === 'globe') {
    return geoOrthographic()
      .rotate([-view.lambda, -view.phi])
      .fitExtent(
        [
          [10, 10],
          [width - 10, height - 10],
        ],
        { type: 'Sphere' },
      )
      // Zoom on a globe scales the sphere itself rather than transforming the group, so
      // coastlines stay crisp and the horizon stays a true circle.
      .scale(
        geoOrthographic()
          .fitExtent(
            [
              [10, 10],
              [width - 10, height - 10],
            ],
            { type: 'Sphere' },
          )
          .scale() * view.k,
      )
  }
  return geoEqualEarth().fitExtent(
    [
      [6, 6],
      [width - 6, height - 6],
    ],
    POPULATED_WORLD,
  )
}

/** Degrees of rotation per pixel dragged, scaled so zooming in slows rotation to match. */
export function dragToRotation(dx: number, dy: number, k: number) {
  const sensitivity = 0.25 / Math.max(1, k * 0.6)
  return { dLambda: dx * sensitivity, dPhi: -dy * sensitivity }
}

/**
 * Rotation that brings a point to the centre of the globe.
 * Needed because a focal country selected from the table may be on the far side, where its
 * arcs would be invisible -- so selection has to bring it into view.
 */
export function rotationFor(coordinates: [number, number]) {
  return { lambda: coordinates[0], phi: clampPhi(coordinates[1]) }
}

/** Shortest signed angular distance from a to b, for rotating the short way round. */
export function shortestDelta(a: number, b: number): number {
  return ((((b - a + 180) % 360) + 360) % 360) - 180
}
