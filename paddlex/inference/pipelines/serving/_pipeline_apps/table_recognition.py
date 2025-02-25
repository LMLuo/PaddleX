# copyright (c) 2024 PaddlePaddle Authors. All Rights Reserve.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing_extensions import Annotated, TypeAlias

from .....utils import logging
from ...table_recognition import TableRecPipeline
from .. import utils as serving_utils
from ..app import AppConfig, create_app
from ..models import Response, ResultResponse


class InferenceParams(BaseModel):
    maxLongSide: Optional[Annotated[int, Field(gt=0)]] = None


class InferRequest(BaseModel):
    image: str
    inferenceParams: Optional[InferenceParams] = None


Point: TypeAlias = Annotated[List[int], Field(min_length=2, max_length=2)]
BoundingBox: TypeAlias = Annotated[List[float], Field(min_length=4, max_length=4)]


class Table(BaseModel):
    bbox: BoundingBox
    html: str


class InferResult(BaseModel):
    tables: List[Table]
    layoutImage: str
    ocrImage: str


def create_pipeline_app(pipeline: TableRecPipeline, app_config: AppConfig) -> FastAPI:
    app, ctx = create_app(
        pipeline=pipeline, app_config=app_config, app_aiohttp_session=True
    )

    @app.post(
        "/table-recognition", operation_id="infer", responses={422: {"model": Response}}
    )
    async def _infer(request: InferRequest) -> ResultResponse[InferResult]:
        pipeline = ctx.pipeline
        aiohttp_session = ctx.aiohttp_session

        if request.inferenceParams:
            max_long_side = request.inferenceParams.maxLongSide
            if max_long_side:
                raise HTTPException(
                    status_code=422,
                    detail="`max_long_side` is currently not supported.",
                )

        try:
            file_bytes = await serving_utils.get_raw_bytes(
                request.image, aiohttp_session
            )
            image = serving_utils.image_bytes_to_array(file_bytes)

            result = (await pipeline.infer(image))[0]

            tables: List[Table] = []
            for item in result["table_result"]:
                tables.append(
                    Table(
                        bbox=item["layout_bbox"],
                        html=item["html"],
                    )
                )
            layout_image_base64 = serving_utils.base64_encode(
                serving_utils.image_to_bytes(result["layout_result"].img)
            )
            ocr_image_base64 = serving_utils.base64_encode(
                serving_utils.image_to_bytes(result["ocr_result"].img)
            )

            return ResultResponse(
                logId=serving_utils.generate_log_id(),
                errorCode=0,
                errorMsg="Success",
                result=InferResult(
                    tables=tables,
                    layoutImage=layout_image_base64,
                    ocrImage=ocr_image_base64,
                ),
            )

        except Exception as e:
            logging.exception(e)
            raise HTTPException(status_code=500, detail="Internal server error")

    return app
