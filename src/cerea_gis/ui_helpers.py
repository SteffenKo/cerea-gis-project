import folium
import geopandas as gpd


def safe_widget_suffix(value: str):
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)


def create_map(polygon, ordered_line_items):
    gdf_poly = None
    if polygon is not None:
        gdf_poly = gpd.GeoDataFrame([{"geometry": polygon}], crs="EPSG:25832").to_crs(
            epsg=4326
        )
    gdf_lines = gpd.GeoDataFrame(
        [
            {
                "order": i + 1,
                "geometry": item["geometry"],
            }
            for i, item in enumerate(ordered_line_items)
        ],
        crs="EPSG:25832",
    ).to_crs(epsg=4326)

    if gdf_poly is not None:
        center = gdf_poly.geometry.centroid.iloc[0]
    else:
        center = gdf_lines.geometry.unary_union.centroid
    m = folium.Map(location=[center.y, center.x], zoom_start=16)

    if gdf_poly is not None:
        folium.GeoJson(
            gdf_poly,
            name="Field",
            style_function=lambda _: {
                "color": "green",
                "weight": 2,
                "fillOpacity": 0.2,
            },
        ).add_to(m)

    for _, row in gdf_lines.iterrows():
        folium.GeoJson(
            row["geometry"],
            style_function=lambda _: {
                "color": "blue",
                "weight": 3,
            },
        ).add_to(m)

        midpoint = row["geometry"].interpolate(0.5, normalized=True)
        folium.Marker(
            location=[midpoint.y, midpoint.x],
            icon=folium.DivIcon(
                html=f"""
                <div style="
                    font-size: 14px;
                    font-weight: bold;
                    color: black;
                    background-color: white;
                    border: 2px solid black;
                    border-radius: 12px;
                    text-align: center;
                    width: 24px;
                    height: 24px;
                    line-height: 20px;
                ">
                    {row['order']}
                </div>
                """
            ),
        ).add_to(m)

    folium.LayerControl().add_to(m)
    return m
